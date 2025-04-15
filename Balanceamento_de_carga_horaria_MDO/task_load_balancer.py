# task_load_balancer.py
# Aplicação para análise e balanceamento de carga horária por função utilizando Streamlit
# Autor: [Seu Nome]
# Descrição: Lê tarefas de um arquivo Excel/CSV, calcula carga horária semanal, mensal e anual,
# permite análise interativa, exporta relatórios e gráficos em Excel e PDF.

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
from io import BytesIO
from fpdf import FPDF
import tempfile
import plotly.express as px

# Configuração inicial da aplicação Streamlit
st.set_page_config(page_title="Balanceador de Tarefas", layout="wide")
st.title("Análise e Balanceamento de Carga por Função")

# Upload de arquivo CSV ou Excel contendo as tarefas
uploaded_file = st.file_uploader("Envie um arquivo CSV com as tarefas", type=["csv", "xlsx"])
if uploaded_file:
    if uploaded_file.name.endswith(".xlsx"):
        df = pd.read_excel(uploaded_file)
    else:
        df = pd.read_csv(uploaded_file)

    st.subheader("Tarefas Recebidas")
    st.dataframe(df)

    col_filtros = st.columns(3)
    with col_filtros[0]:
        etapa_selecionada = st.selectbox("Filtrar por ETAPA", options=["Todas"] + sorted(df['ETAPA'].dropna().unique().tolist()))
    with col_filtros[1]:
        atividade_selecionada = st.selectbox("Filtrar por ATIVIDADE", options=["Todas"] + sorted(df['ATIVIDADE'].dropna().unique().tolist()))
    with col_filtros[2]:
        funcao_selecionada = st.selectbox("Filtrar por FUNÇÃO", options=["Todas"] + sorted(df['FUNÇÃO'].dropna().unique().tolist()))

    if etapa_selecionada != "Todas":
        df = df[df['ETAPA'] == etapa_selecionada]
    if atividade_selecionada != "Todas":
        df = df[df['ATIVIDADE'] == atividade_selecionada]
    if funcao_selecionada != "Todas":
        df = df[df['FUNÇÃO'] == funcao_selecionada]

    if 'C.H ATUAL' in df.columns and 'FUNÇÃO' in df.columns:
        def time_to_hours(t):
            if pd.isna(t):
                return 0
            return t.hour + t.minute / 60 + t.second / 3600

        df['duracao_horas'] = df['C.H ATUAL'].apply(time_to_hours)
        tarefas_sem_frequencia = df[df['FREQUÊNCIA'].isna()].copy()
        df = df[~df['FREQUÊNCIA'].isna()]  # Remove tarefas sem frequência
        df['FREQUÊNCIA'] = df['FREQUÊNCIA'].astype(str).str.strip().str.lower()

        def freq_para_mes(freq):
            mapa = {
                'diária': 20,
                'diario': 20,
                'diariamente': 20,
                'semanal': 4,
                'quinzenal': 2,
                'mensal': 1,
                'bimestral': 0.5,
                'trimestral': 1/3,
                'semestral': 1/6,
                'anual': 1/12
            }
            return mapa.get(freq.strip(), 0)

        df['frequencia_mes'] = df['FREQUÊNCIA'].apply(freq_para_mes)
        df['carga_mensal'] = df['duracao_horas'] * df['frequencia_mes']
        df['carga_semanal'] = df['carga_mensal'] / 4
        df['carga_anual'] = df['carga_mensal'] * 12

        # garantir que todas as funções do dataset sejam representadas, até as com carga zero
        todas_funcoes = df['FUNÇÃO'].dropna().unique()
        carga_por_funcao = df.groupby('FUNÇÃO').agg(
            horas_semanais=('carga_semanal', 'sum'),
            horas_mensais=('carga_mensal', 'sum'),
            horas_anuais=('carga_anual', 'sum'),
            tarefas_total=('duracao_horas', 'count')
        ).reindex(todas_funcoes).fillna(0).reset_index()

        carga_por_funcao['media_diaria'] = carga_por_funcao['horas_semanais'] / 5

        st.subheader("Defina os limites máximos de carga horária")
        limite_diario = st.number_input("Limite diário por função (h)", min_value=1, value=9)
        limite_semanal = st.number_input("Limite semanal por função (h)", min_value=1, value=44)
        limite_mensal = st.number_input("Limite mensal por função (h)", min_value=1, value=176)
        limite_anual = st.number_input("Limite anual por função (h)", min_value=1, value=2112)

        carga_por_funcao['alerta_diaria'] = np.where(carga_por_funcao['media_diaria'] > limite_diario, '⚠️ Acima do limite diário', '')
        carga_por_funcao['alerta_semanal'] = np.where(carga_por_funcao['horas_semanais'] > limite_semanal, '⚠️ Acima do limite semanal', '')
        carga_por_funcao['alerta_mensal'] = np.where(carga_por_funcao['horas_mensais'] > limite_mensal, '⚠️ Acima do limite mensal', '')
        carga_por_funcao['alerta_anual'] = np.where(carga_por_funcao['horas_anuais'] > limite_anual, '⚠️ Acima do limite anual', '')

        criterio_ocioso = st.selectbox("Critério para classificar ociosidade", ["mensal", "semanal"])
        percentual_ocioso = st.slider("% da carga para considerar função ociosa", min_value=0.1, max_value=1.0, value=0.8, step=0.05)

        if criterio_ocioso == "mensal":
            carga_por_funcao['ocioso'] = np.where(
                carga_por_funcao['horas_mensais'] < (limite_mensal * percentual_ocioso),
                '🟢 Abaixo de 80% da carga',
                ''
            )
        else:
            carga_por_funcao['ocioso'] = np.where(
                carga_por_funcao['horas_semanais'] < (limite_semanal * percentual_ocioso),
                '🟢 Abaixo de 80% da carga',
                ''
            )

        st.subheader("Filtrar análise por status")
        filtro_status = st.selectbox("Mostrar", ["Todos", "Apenas sobrecarregados", "Apenas ociosos"])
        if filtro_status == "Apenas sobrecarregados":
            carga_por_funcao = carga_por_funcao[carga_por_funcao['horas_mensais'] > limite_mensal]
        elif filtro_status == "Apenas ociosos":
            carga_por_funcao = carga_por_funcao[carga_por_funcao['ocioso'] != '']

        st.subheader("Análise de Carga por Função")
        ocultar_zeradas = st.checkbox("Ocultar funções com 0 horas e 0 tarefas")
        if ocultar_zeradas:
            carga_por_funcao = carga_por_funcao[
                (carga_por_funcao['horas_mensais'] > 0) | (carga_por_funcao['tarefas_total'] > 0)
            ]
        st.dataframe(carga_por_funcao)

        if not tarefas_sem_frequencia.empty:
            st.subheader("Tarefas ignoradas por falta de frequência")
        st.dataframe(tarefas_sem_frequencia)

        st.download_button(
            label="📥 Baixar tarefas sem frequência",
            data=tarefas_sem_frequencia.to_csv(index=False).encode('utf-8'),
            file_name="tarefas_sem_frequencia.csv",
            mime="text/csv"
        )

        st.subheader("Tarefas que contribuem para sobrecarga")
        tarefas_alerta = df[df['FUNÇÃO'].isin(carga_por_funcao[carga_por_funcao['horas_mensais'] > limite_mensal]['FUNÇÃO'])]
        st.dataframe(tarefas_alerta)

        def gerar_excel_situacoes(df_tarefas, df_resumo):
            funcoes_sobrecarregadas = df_resumo[df_resumo['horas_mensais'] > limite_mensal]['FUNÇÃO']
            funcoes_ociosas = df_resumo[df_resumo['ocioso'] != '']['FUNÇÃO']
            tarefas_sobrecarregadas = df_tarefas[df_tarefas['FUNÇÃO'].isin(funcoes_sobrecarregadas)]
            tarefas_ociosas = df_tarefas[df_tarefas['FUNÇÃO'].isin(funcoes_ociosas)]
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                tarefas_sobrecarregadas.to_excel(writer, index=False, sheet_name='Funções Sobrecarregadas')
                tarefas_ociosas.to_excel(writer, index=False, sheet_name='Funções Ociosas')
            return output.getvalue()

        def gerar_excel_download(df):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Carga por Função')
            return output.getvalue()

        def gerar_excel_tarefas_alerta(df):
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Tarefas Críticas')
            return output.getvalue()

        def gerar_pdf_resumo(df):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt="Relatorio de Carga por Funcao", ln=True, align='C')
            for _, row in df.iterrows():
                alerta = row['alerta_mensal'].replace('⚠️', '[!]') if isinstance(row['alerta_mensal'], str) else ''
                ocioso = row['ocioso'].replace('🟢', '[OK]') if isinstance(row['ocioso'], str) else ''
                linha = f"{row['FUNÇÃO']}: {row['horas_mensais']:.1f}h/mes {alerta} {ocioso} ({row['horas_mensais']/limite_mensal:.0%})"
                pdf.cell(200, 10, txt=linha.encode('latin-1', 'ignore').decode('latin-1'), ln=True)

            pdf.add_page()
            pdf.set_font("Arial", size=10)
            pdf.cell(200, 10, txt="Grafico de Carga Semanal por Funcao", ln=True, align='C')
            fig, ax = plt.subplots()
            bars = ax.bar(df['FUNÇÃO'], df['horas_semanais'])
            ax.axhline(44, color='red', linestyle='--')
            for bar, hs in zip(bars, df['horas_semanais']):
                if hs > 44:
                    bar.set_color('orange')
                elif hs < 176 * 0.5 / 4:
                    bar.set_color('green')
            ax.set_ylabel("Horas Semanais")
            ax.set_title("Carga por Funcao")
            img_path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
            fig.savefig(img_path)
            plt.close(fig)
            pdf.image(img_path, x=10, y=30, w=180)
            return pdf.output(dest='S').encode('latin-1')

        st.download_button("📥 Baixar funções sobrecarregadas/ociosas", data=gerar_excel_situacoes(df, carga_por_funcao), file_name="funcoes_situacoes.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("📥 Baixar análise de carga em Excel", data=gerar_excel_download(carga_por_funcao), file_name="analise_carga_funcoes.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("📥 Baixar tarefas que causam sobrecarga", data=gerar_excel_tarefas_alerta(tarefas_alerta), file_name="tarefas_sobrecarga.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("📥 Baixar relatório em PDF", data=gerar_pdf_resumo(carga_por_funcao), file_name="relatorio_carga_funcoes.pdf", mime="application/pdf")

        carga_por_funcao['diferenca_horas'] = limite_mensal - carga_por_funcao['horas_mensais']
        st.subheader("Gráfico Interativo de Carga Semanal")
        grafico = px.bar(
            carga_por_funcao,
            x='FUNÇÃO',
            y='horas_semanais',
            color=carga_por_funcao['horas_semanais'] > limite_semanal,
            color_discrete_map={True: 'orange', False: 'blue'},
            labels={'horas_semanais': 'Horas Semanais', 'FUNÇÃO': 'Função'},
            title='Carga por Função',
            hover_data=['FUNÇÃO', 'horas_semanais', 'diferenca_horas']
        )
        grafico.add_shape(
            type="line",
            x0=-0.5,
            x1=len(carga_por_funcao)-0.5,
            y0=float(limite_semanal),
            y1=float(limite_semanal),
            line=dict(color="red", width=2, dash="dash")
        )
        grafico.update_layout(showlegend=False)
        st.plotly_chart(grafico, use_container_width=True)

        st.subheader("Gráfico Interativo de Funções Ociosas")
        funcoes_ociosas_df = carga_por_funcao[carga_por_funcao['ocioso'] != '']
        if not funcoes_ociosas_df.empty:
            grafico_ociosas = px.bar(
                funcoes_ociosas_df,
                x='FUNÇÃO',
                y='horas_semanais',
                color_discrete_sequence=['green'],
                labels={'horas_semanais': 'Horas Semanais', 'FUNÇÃO': 'Função'},
                title='Funções com baixa ocupação',
                hover_data=['FUNÇÃO', 'horas_semanais', 'diferenca_horas']
            )
            grafico_ociosas.update_layout(showlegend=False)
            st.plotly_chart(grafico_ociosas, use_container_width=True)
        else:
            st.info("Nenhuma função identificada como ociosa com base no critério atual.")

# Parte de redistribuição permanece inalterada...


