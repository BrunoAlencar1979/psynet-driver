from sqlalchemy import Column, Integer, String, Float, DateTime
from database import Base
import datetime

class Lancamento(Base):
    __tablename__ = "lancamentos"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), index=True, default="bruno_admin") # <--- A NOVA COLUNA AQUI
    tipo = Column(String(50), index=True)
    valor = Column(Float)
    descricao = Column(String(255))
    data_hora = Column(DateTime, default=datetime.datetime.utcnow)
