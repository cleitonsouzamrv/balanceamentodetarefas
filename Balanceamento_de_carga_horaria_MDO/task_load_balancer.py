import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from io import BytesIO
from fpdf import FPDF
import tempfile
import plotly.express as px
import datetime

st.set_page_config(page_title="Balanceador de Tarefas", layout="wide")
st.title("⚖️ Análise e Balanceamento de Carga por Categoria")

uploaded_file = st.file_uploader("Envie um arquivo Excel com as tarefas", type=["xlsx", "csv"])
if uploaded_file:
    if uploaded_file.name.endswith(".xlsx"):
        df = pd.read_excel(uploaded_file)
    else:
        df = pd.read_csv(uploaded_file)

    st.subheader("Tarefas Recebidas")
    st.dataframe(df.head(31))

    df['CATEGORIA'] = df['CATEGORIA'].fillna('Não Informado')

    col_filtros = st.columns(3)
    with col_filtros[0]:
        etapa_selecionada = st.selectbox("Filtrar por ETAPA", options=["Todas"] + sorted(df['ETAPA'].dropna().unique().tolist()))
    with col_filtros[1]:
        atividade_selecionada = st.selectbox("Filtrar por ATIVIDADE", options=["Todas"] + sorted(df['MACROFLUXO'].dropna().unique().tolist()))
    with col_filtros[2]:
        categoria_selecionada = st.selectbox("Filtrar por CATEGORIA", options=["Todas"] + sorted(df['CATEGORIA'].dropna().unique().tolist()))

    if etapa_selecionada != "Todas":
        df = df[df['ETAPA'] == etapa_selecionada]
    if atividade_selecionada != "Todas":
        df = df[df['DESCRIÇÃO DO PROCESSO'] == atividade_selecionada]
    if categoria_selecionada != "Todas":
        df = df[df['CATEGORIA'] == categoria_selecionada]

    def tempo_para_horas(t):
        if pd.isna(t):
            return 0
        if isinstance(t, str):
            try:
                h, m, s = map(int, t.split(':'))
                return h + m / 60 + s / 3600
            except:
                return 0
        if isinstance(t, datetime.time):
            return t.hour + t.minute / 60 + t.second / 3600
        return 0

    df['duracao_horas'] = df['C.H ATUAL (total para o serviço executado)'].apply(tempo_para_horas)

    tarefas_sem_frequencia = df[df['FREQUÊNCIA'].isna()].copy()
    df = df[~df['FREQUÊNCIA'].isna()]
    df['FREQUÊNCIA'] = df['FREQUÊNCIA'].astype(str).str.lower().str.strip()

    def freq_para_mes(freq):
        mapa = {
            'diária': 20, 'diario': 20, 'diariamente': 20,
            'semanal': 4, 'quinzenal': 2, 'mensal': 1,
            'bimestral': 0.5, 'trimestral': 1/3,
            'semestral': 1/6, 'anual': 1/12
        }
        return mapa.get(freq, 0)

    df['frequencia_mes'] = df['FREQUÊNCIA'].apply(freq_para_mes)
    df['carga_mensal'] = df['duracao_horas'] * df['frequencia_mes']
    df['carga_semanal'] = df['carga_mensal'] / 4
    df['carga_anual'] = df['carga_mensal'] * 12

    todas_categorias = df['CATEGORIA'].dropna().unique()
    carga_por_categoria = df.groupby('CATEGORIA').agg(
        horas_semanais=('carga_semanal', 'sum'),
        horas_mensais=('carga_mensal', 'sum'),
        horas_anuais=('carga_anual', 'sum'),
        tarefas_total=('duracao_horas', 'count')
    ).reindex(todas_categorias).fillna(0).reset_index()

    carga_por_categoria['media_diaria'] = carga_por_categoria['horas_semanais'] / 5

    st.subheader("Defina os limites máximos de carga horária")
    limite_diario = st.number_input("Limite diário por categoria (h)", min_value=1, value=9)
    limite_semanal = st.number_input("Limite semanal por categoria (h)", min_value=1, value=44)
    limite_mensal = st.number_input("Limite mensal por categoria (h)", min_value=1, value=176)
    limite_anual = st.number_input("Limite anual por categoria (h)", min_value=1, value=2112)

    carga_por_categoria['alerta_diaria'] = np.where(carga_por_categoria['media_diaria'] > limite_diario, '⚠️ Acima do limite diário', '')
    carga_por_categoria['alerta_semanal'] = np.where(carga_por_categoria['horas_semanais'] > limite_semanal, '⚠️ Acima do limite semanal', '')
    carga_por_categoria['alerta_mensal'] = np.where(carga_por_categoria['horas_mensais'] > limite_mensal, '⚠️ Acima do limite mensal', '')
    carga_por_categoria['alerta_anual'] = np.where(carga_por_categoria['horas_anuais'] > limite_anual, '⚠️ Acima do limite anual', '')

    criterio_ocioso = st.selectbox("Critério para classificar ociosidade", ["mensal", "semanal"])
    percentual_ocioso = st.slider("% da carga para considerar categoria ociosa", min_value=0.1, max_value=1.0, value=0.8, step=0.05)

    if criterio_ocioso == "mensal":
        carga_por_categoria['ocioso'] = np.where(
            carga_por_categoria['horas_mensais'] < (limite_mensal * percentual_ocioso),
            '🟢 Abaixo de 80% da carga',
            ''
        )
    else:
        carga_por_categoria['ocioso'] = np.where(
            carga_por_categoria['horas_semanais'] < (limite_semanal * percentual_ocioso),
            '🟢 Abaixo de 80% da carga',
            ''
        )

    st.subheader("Análise de Carga por Categoria")
    ocultar_zeradas = st.checkbox("Ocultar categorias com 0 horas e 0 tarefas")
    if ocultar_zeradas:
        carga_por_categoria = carga_por_categoria[
            (carga_por_categoria['horas_mensais'] > 0) | (carga_por_categoria['tarefas_total'] > 0)
        ]
    st.dataframe(carga_por_categoria)

    st.download_button(
        label="📥 Baixar análise de carga por categoria",
        data=carga_por_categoria.to_csv(index=False).encode('utf-8'),
        file_name="carga_por_categoria.csv",
        mime="text/csv"
    )

    fig = px.bar(
        carga_por_categoria,
        x='CATEGORIA',
        y='horas_semanais',
        color=carga_por_categoria['horas_semanais'] > limite_semanal,
        color_discrete_map={True: 'orange', False: 'blue'},
        labels={'horas_semanais': 'Horas Semanais', 'CATEGORIA': 'Categoria'},
        title='Carga por Categoria',
        hover_data=['CATEGORIA', 'horas_semanais']
    )

    fig.add_shape(
        type="line",
        x0=-0.5,
        x1=len(carga_por_categoria)-0.5,
        y0=float(limite_semanal),
        y1=float(limite_semanal),
        line=dict(color="red", width=2, dash="dash")
    )

    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    categorias_ociosas = carga_por_categoria[carga_por_categoria['ocioso'] != '']
    if not categorias_ociosas.empty:
        st.subheader("Categorias com Baixa Ocupação")
        fig_ociosas = px.bar(
            categorias_ociosas,
            x='CATEGORIA',
            y='horas_semanais',
            color_discrete_sequence=['green'],
            labels={'horas_semanais': 'Horas Semanais', 'CATEGORIA': 'Categoria'},
            title='Categorias Ociosas',
            hover_data=['CATEGORIA', 'horas_semanais']
        )
        fig_ociosas.update_layout(showlegend=False)
        st.plotly_chart(fig_ociosas, use_container_width=True)
    else:
        st.info("Nenhuma categoria identificada como ociosa com base no critério atual.")
