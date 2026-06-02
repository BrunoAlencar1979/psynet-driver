from sqlalchemy import Column, Integer, String, Float, DateTime
from database import Base
from datetime import datetime

class Lancamento(Base):
    __tablename__ = "lancamentos"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String(50), index=True)       # ganho ou despesa
    valor = Column(Float)
    descricao = Column(String(255))
    data_hora = Column(DateTime, default=datetime.utcnow)