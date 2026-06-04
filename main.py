import re
import unicodedata
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, Query, Path, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy import func

import models
from database import engine, get_db

# Garante que as tabelas são criadas no banco de dados
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="PsyNet Command SaaS")

# Configuração OBRIGATÓRIA de Segurança (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class NotificacaoApp(BaseModel):
    tipo: str
    valor: float
    descricao: str

class NotificacaoBruta(BaseModel):
    app_origem: str
    titulo: str
    texto_notificacao: str

@app.post("/api/lancamentos")
# ADICIONADO: Exige o user_id no cabeçalho da requisição
def registrar_lancamento(dados: NotificacaoApp, user_id: str = Header(...), db: Session = Depends(get_db)):
    hora_brasilia = datetime.utcnow() - timedelta(hours=3)
    
    # Grava no banco com a etiqueta do utilizador correto
    novo = models.Lancamento(tipo=dados.tipo, valor=dados.valor, descricao=dados.descricao, data_hora=hora_brasilia, user_id=user_id)
    db.add(novo)
    db.commit()
    return {"status": "sucesso"}

@app.delete("/api/lancamentos/{item_id}")
def deletar_lancamento(item_id: int = Path(...), user_id: str = Header(...), db: Session = Depends(get_db)):
    # Garante que o utilizador só apaga os SEUS PRÓPRIOS lançamentos
    item = db.query(models.Lancamento).filter(models.Lancamento.id == item_id, models.Lancamento.user_id == user_id).first()
    if item:
        db.delete(item)
        db.commit()
        return {"status": "sucesso", "mensagem": "Registo apagado."}
    return {"status": "erro", "mensagem": "Acesso negado ou registo não encontrado."}

@app.get("/api/historico")
def pegar_historico(user_id: str = Header(...), db: Session = Depends(get_db)):
    # Filtra apenas o histórico de quem está a pedir
    itens = db.query(models.Lancamento).filter(models.Lancamento.user_id == user_id).order_by(models.Lancamento.data_hora.desc()).limit(30).all()
    return [{"id": i.id, "tipo": i.tipo, "valor": i.valor, "descricao": i.descricao, "hora": i.data_hora.strftime("%H:%M")} for i in itens]

@app.post("/api/captura_bruta")
def processar_notificacao_bruta(dados: NotificacaoBruta, user_id: str = Header(...), db: Session = Depends(get_db)):
    texto_completo = f"{dados.titulo} {dados.texto_notificacao}".lower()
    texto_sem_acento = ''.join(c for c in unicodedata.normalize('NFD', texto_completo) if unicodedata.category(c) != 'Mn')
    
    valor = 0.0
    contexto_voz = ""
    
    match = re.search(r'(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:reais|real)?', texto_completo)
    if not match: return {"status": "ignorado"}

    valor_str = match.group(1).replace('.', '').replace(',', '.')
    valor = float(valor_str)
    
    tipo, descricao, salvar = "despesa", "Gasto Detetado", False
    favorecido = ""
    match_nome = re.search(r'\b(?:em|para|de)\s+(?:o\s+|a\s+)?([a-z0-9\s]+?)(?:,|\.|$|-|no valor)', texto_sem_acento)
    if match_nome:
        pedacos = match_nome.group(1).strip().split()
        if len(pedacos) > 0 and pedacos[0] != "r": favorecido = " ".join(pedacos[:2]).title()
            
    palavras_limpar = ['um', 'uma', 'reais', 'real', 'transferencia', 'pix', 'voce', 'conta', 'sucesso', 'concluido']
    if favorecido.lower() in palavras_limpar: favorecido = ""
    if not favorecido and len(dados.titulo) < 20 and "R$" not in dados.titulo: favorecido = dados.titulo.title()

    if dados.app_origem == "JARVIS":
        contexto = texto_completo
        for p in ["gastei", "recebi", "ganhei", "paguei", "comprei", "r$", "reais", "real", match.group(1), match.group(0)]:
            contexto = contexto.replace(p, "")
        contexto = re.sub(r'^\s*(com|de|da|do|em|por|na|no|para)\s+', '', contexto.strip())
        contexto_voz = contexto.strip().capitalize()
        
        if "gastei" in texto_sem_acento or "paguei" in texto_sem_acento or "comprei" in texto_sem_acento:
            descricao = f"Gasto: {contexto_voz}" if contexto_voz else "Gasto Manual"
            tipo, salvar = "despesa", True
        else:
            descricao = f"Receita: {contexto_voz}" if contexto_voz else "Receita Manual"
            tipo, salvar = "ganho", True
            
    elif "uber" in dados.app_origem.lower() or "99" in dados.app_origem.lower() or "indrive" in dados.app_origem.lower():
        tipo, descricao, salvar = "ganho", f"Mobilidade", True
        
    elif "pix" in texto_sem_acento or "transferencia" in texto_sem_acento:
        if "recebeu" in texto_sem_acento or "recebido" in texto_sem_acento or "entrou" in texto_sem_acento:
            descricao = f"Pix Recebido: {favorecido}" if favorecido else "Receita Pix"
            tipo, salvar = "ganho", True
        else:
            descricao = f"Pix Enviado: {favorecido}" if favorecido else "Pix Enviado"
            tipo, salvar = "despesa", True

    elif "posto" in texto_sem_acento or "combust" in texto_sem_acento or "gasolina" in texto_sem_acento:
        tipo, descricao, salvar = "despesa", "Abastecimento", True
        
    elif "compra" in texto_sem_acento or "debito" in texto_sem_acento or "pagamento" in texto_sem_acento:
        descricao = f"Gasto: {favorecido}" if favorecido else "Gasto Cartão"
        tipo, salvar = "despesa", True

    if salvar:
        hora_brasilia = datetime.utcnow() - timedelta(hours=3)
        limite_tempo = hora_brasilia - timedelta(minutes=3)
        
        # O Bloqueio de duplicatas agora também verifica se foi o MESMO utilizador
        duplicata = db.query(models.Lancamento).filter(
            models.Lancamento.user_id == user_id,
            models.Lancamento.valor == valor,
            models.Lancamento.tipo == tipo,
            models.Lancamento.data_hora >= limite_tempo
        ).first()
        
        if duplicata: return {"status": "ignorado", "motivo": "duplicata_recente"}

        db.add(models.Lancamento(tipo=tipo, valor=valor, descricao=descricao, data_hora=hora_brasilia, user_id=user_id))
        db.commit()
        return {"status": "sucesso", "categorizado_como": descricao, "valor": valor}
        
    return {"status": "ignorado"}

@app.get("/api/resumo")
def pegar_resumo_contabil(meta_mensal: float = Query(8000.0), user_id: str = Header(...), db: Session = Depends(get_db)):
    
    def soma_por_filtro(*filtros):
        return db.query(func.sum(models.Lancamento.valor)).filter(models.Lancamento.user_id == user_id, *filtros).scalar() or 0.0

    total_ganhos = soma_por_filtro(models.Lancamento.tipo == "ganho")
    total_gastos = soma_por_filtro(models.Lancamento.tipo == "despesa")
    
    faturamento_mobilidade = soma_por_filtro(models.Lancamento.tipo == "ganho", models.Lancamento.descricao.like("%Mobilidade%"))
    receita_pix = soma_por_filtro(models.Lancamento.tipo == "ganho", models.Lancamento.descricao.like("%Pix%"))
    receita_manual = soma_por_filtro(models.Lancamento.tipo == "ganho", models.Lancamento.descricao.like("%Manual%"))

    fundo = total_ganhos * 0.05
    depreciacao = total_ganhos * 0.08  
    lucro_real = total_ganhos - total_gastos - fundo - depreciacao

    dias_no_mes = 30
    dias_trabalhados = db.query(func.count(func.distinct(func.date(models.Lancamento.data_hora)))).filter(models.Lancamento.user_id == user_id).scalar() or 1
    projecao_mensal = (total_ganhos / dias_trabalhados) * dias_no_mes
    
    dias_restantes = dias_no_mes - dias_trabalhados if (dias_no_mes - dias_trabalhados) > 0 else 1
    falta_para_meta = meta_mensal - total_ganhos
    
    return {
        "fluxo": {
            "total_bruto": total_ganhos, 
            "lucro_real": lucro_real, 
            "gastos": total_gastos, 
            "fundo": fundo, 
            "depreciacao": depreciacao
        },
        "fontes": {
            "mobilidade": faturamento_mobilidade, 
            "transferencias_pix": receita_pix, 
            "dinheiro_especie": receita_manual
        }, 
        "estrategia": {
            "meta_semanal": meta_mensal / 4.33, 
            "projecao_mensal": projecao_mensal, 
            "meta_diaria_ajustada": (falta_para_meta / dias_restantes) if falta_para_meta > 0 else 0.0
        }
    }
