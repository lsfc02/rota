# presentation/chat.py
import streamlit as st

def show(rag_cls, colecao: str):
    """
    rag_cls: classe que provê verify() ou ask_question().
    colecao: nome da coleção selecionada na sidebar.
    """
    st.header("💬 Chat RAG")
    svc = rag_cls()

    # Se a classe tiver load_collection (por ex., em RAG puro), use-a.
    if colecao:
        if hasattr(svc, "load_collection"):
            ok = svc.load_collection(colecao)
            if not ok:
                st.error(f"Não encontrou documentos em data/collections/{colecao}")
                return
    else:
        st.warning("Selecione uma coleção na sidebar")
        return

    pergunta = st.text_input("Pergunta:")
    if st.button("Enviar"):
        with st.spinner("Pensando…"):
            # tenta método de chat, senão usa verify (rota)
            if hasattr(svc, "ask_question"):
                resposta = svc.ask_question(pergunta)
            else:
                resposta = svc.verify([])  # ou passe rota real se fizer sentido
        st.markdown(resposta)
