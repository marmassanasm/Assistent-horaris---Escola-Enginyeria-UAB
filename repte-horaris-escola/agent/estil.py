"""agent/estil.py: aspecte de l'aplicació (tipus de lletra, colors, espaiats)."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:wght@600&display=swap');

html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif; }
h1, h2, h3 { font-family: 'Source Serif 4', serif !important; font-weight: 600; letter-spacing: -0.01em; }

/* amaga la barra superior i el peu de Streamlit */
header[data-testid="stHeader"], footer, #MainMenu { visibility: hidden; height: 0; }
.block-container { padding-top: 2rem; max-width: 1250px; }

/* pestanyes */
button[data-baseweb="tab"] { font-weight: 500; font-size: 0.98rem; padding: 0.6rem 1.1rem; }
button[data-baseweb="tab"][aria-selected="true"] { color: #1F5C4A; }
div[data-baseweb="tab-highlight"] { background-color: #1F5C4A; }

/* botons */
.stButton > button, .stDownloadButton > button {
  border-radius: 6px; border: 1px solid #1F5C4A; font-weight: 500; padding: 0.5rem 1.2rem; box-shadow: none;
}
.stButton > button[kind="primary"] { background: #1F5C4A; color: white; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: #143d31; color: #143d31; }
.stButton > button[kind="primary"]:hover { background: #143d31; color: white; }

/* camps i taules */
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div { border-radius: 6px; }
div[data-testid="stDataFrame"] { border: 1px solid #DAD9D0; border-radius: 6px; }
</style>
"""


def aplica():
    st.markdown(CSS, unsafe_allow_html=True)