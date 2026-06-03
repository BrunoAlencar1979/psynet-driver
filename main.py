import re
import unicodedata
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy import func

import models
from database import engine, get_db

# Garante que as tabelas são criadas no banco de dados
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="PsyNet Command")

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
def registrar_lancamento(dados: NotificacaoApp, db: Session = Depends(get_db)):
    novo = models.Lancamento(tipo=dados.tipo, valor=dados.valor, descricao=dados.descricao, data_hora=datetime.now())
    db.add(novo)
    db.commit()
    return {"status": "sucesso"}

@app.delete("/api/lancamentos/{item_id}")
def deletar_lancamento(item_id: int = Path(...), db: Session = Depends(get_db)):
    item = db.query(models.Lancamento).filter(models.Lancamento.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        return {"status": "sucesso", "mensagem": "Registo apagado."}
    return {"status": "erro"}

@app.get("/api/historico")
def pegar_historico(db: Session = Depends(get_db)):
    itens = db.query(models.Lancamento).order_by(models.Lancamento.data_hora.desc()).limit(30).all()
    return [{"id": i.id, "tipo": i.tipo, "valor": i.valor, "descricao": i.descricao, "hora": i.data_hora.strftime("%H:%M")} for i in itens]

@app.post("/api/captura_bruta")
def processar_notificacao_bruta(dados: NotificacaoBruta, db: Session = Depends(get_db)):
    print(f"\n📡 [INTERCEÇÃO] {dados.app_origem}: {dados.titulo} | {dados.texto_notificacao}")
    texto_completo = f"{dados.titulo} {dados.texto_notificacao}".lower()
    
    # Remover todos os acentos para a IA não se confundir
    texto_sem_acento = ''.join(c for c in unicodedata.normalize('NFD', texto_completo) if unicodedata.category(c) != 'Mn')
    
    valor = 0.0
    contexto_voz = ""
    
    # Caçador Universal de Dinheiro
    match = re.search(r'(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:reais|real)?', texto_completo)
    if not match:
        return {"status": "ignorado"}

    valor_str = match.group(1).replace('.', '').replace(',', '.')
    valor = float(valor_str)
    
    tipo, descricao, salvar = "despesa", "Gasto Detetado", False

    # O DETETIVE DA INTELIGÊNCIA ARTIFICIAL (Extrai nomes e locais)
    favorecido = ""
    match_nome = re.search(r'\b(?:em|para|de)\s+([a-z0-9\s]+)(?:,|\.|$)', texto_sem_acento)
    if match_nome:
        pedacos = match_nome.group(1).strip().split()
        if len(pedacos) > 0:
            favorecido = " ".join(pedacos[:2]).title()
            
    palavras_limpar = ['um', 'uma', 'o', 'a', 'reais', 'real', 'transferencia', 'pix']
    if favorecido.lower() in palavras_limpar:
        favorecido = ""

    if not favorecido and len(dados.titulo) < 20 and "R$" not in dados.titulo:
        favorecido = dados.titulo.title()

    # Processamento JARVIS (Voz)
    if dados.app_origem == "JARVIS":
        contexto = texto_completo
        palavras_remover = ["gastei", "recebi", "ganhei", "paguei", "comprei", "r$", "reais", "real", match.group(1), match.group(0)]
        for p in palavras_remover:
            contexto = contexto.replace(p, "")
        contexto = re.sub(r'^\s*(com|de|da|do|em|por|na|no|para)\s+', '', contexto.strip())
        contexto_voz = contexto.strip().capitalize()
        
        if "gastei" in texto_sem_acento or "paguei" in texto_sem_acento or "comprei" in texto_sem_acento:
            descricao = f"Gasto: {contexto_voz}" if contexto_voz else "Gasto Manual"
            tipo, salvar = "despesa", True
        else:
            descricao = f"Receita: {contexto_voz}" if contexto_voz else "Receita Manual"
            tipo, salvar = "ganho", True
            
    # Processamento de Aplicativos
    elif "uber" in dados.app_origem.lower() or "99" in dados.app_origem.lower() or "indrive" in dados.app_origem.lower():
        tipo, descricao, salvar = "ganho", f"Mobilidade", True
        
    elif "pix" in texto_sem_acento and ("recebeu" in texto_sem_acento or "transferencia" in texto_sem_acento or "concluid" in texto_sem_acento or "sucesso" in texto_sem_acento):
        descricao = f"Pix: {favorecido}" if favorecido else "Receita Pix"
        tipo, salvar = "ganho", True
        
    elif "posto" in texto_sem_acento or "combust" in texto_sem_acento or "gasolina" in texto_sem_acento:
        tipo, descricao, salvar = "despesa", "Abastecimento", True
        
    elif "compra" in texto_sem_acento or "debito" in texto_sem_acento or "pagamento" in texto_sem_acento:
        descricao = f"Gasto: {favorecido}" if favorecido else "Gasto Cartão"
        tipo, salvar = "despesa", True

    if salvar:
        # A BARREIRA FINAL DE SEGURANÇA (Evita duplicação nos últimos 3 minutos)
        limite_tempo = datetime.now() - timedelta(minutes=3)
        duplicata = db.query(models.Lancamento).filter(
            models.Lancamento.valor == valor,
            models.Lancamento.tipo == tipo,
            models.Lancamento.data_hora >= limite_tempo
        ).first()
        
        if duplicata:
            print(f"⚠️ [DUPLICATA BLOQUEADA] {descricao} - R$ {valor:.2f}")
            return {"status": "ignorado", "motivo": "duplicata_recente"}

        db.add(models.Lancamento(tipo=tipo, valor=valor, descricao=descricao, data_hora=datetime.now()))
        db.commit()
        print(f"✅ [CONTABILIZADO] {descricao} | R$ {valor:.2f}")
        return {"status": "sucesso", "categorizado_como": descricao, "valor": valor}
        
    return {"status": "ignorado"}

@app.get("/api/resumo")
def pegar_resumo_contabil(meta_mensal: float = Query(8000.0), db: Session = Depends(get_db)):
    total_ganhos = db.query(func.sum(models.Lancamento.valor)).filter(models.Lancamento.tipo == "ganho").scalar() or 0.0
    total_gastos = db.query(func.sum(models.Lancamento.valor)).filter(models.Lancamento.tipo == "despesa").scalar() or 0.0
    
    faturamento_mobilidade = db.query(func.sum(models.Lancamento.valor)).filter(
        models.Lancamento.tipo == "ganho", models.Lancamento.descricao.like("%Mobilidade%")
    ).scalar() or 0.0
    
    receita_psynet = db.query(func.sum(models.Lancamento.valor)).filter(
        models.Lancamento.tipo == "ganho", models.Lancamento.descricao.like("%PsyNet%")
    ).scalar() or 0.0

    receita_manual = db.query(func.sum(models.Lancamento.valor)).filter(
        models.Lancamento.tipo == "ganho", models.Lancamento.descricao.like("%Manual%")
    ).scalar() or 0.0

    fundo = total_ganhos * 0.05
    depreciacao = total_ganhos * 0.08  
    lucro_real = total_ganhos - total_gastos - fundo - depreciacao

    dias_no_mes = 30
    dias_trabalhados = db.query(func.count(func.distinct(func.date(models.Lancamento.data_hora)))).scalar() or 1
    projecao_mensal = (total_ganhos / dias_trabalhados) * dias_no_mes
    
    dias_restantes = dias_no_mes - dias_trabalhados if (dias_no_mes - dias_trabalhados) > 0 else 1
    falta_para_meta = meta_mensal - total_ganhos
    
    return {
        "fluxo": {"total_bruto": total_ganhos, "lucro_real": lucro_real, "gastos": total_gastos, "fundo": fundo, "depreciacao": depreciacao},
        "fontes": {"mobilidade": faturamento_mobilidade, "psynet_ti": receita_psynet, "dinheiro_especie": receita_manual}, 
        "estrategia": {"meta_semanal": meta_mensal / 4.33, "projecao_mensal": projecao_mensal, "meta_diaria_ajustada": (falta_para_meta / dias_restantes) if falta_para_meta > 0 else 0.0}
    }
