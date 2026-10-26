import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_PATH = "portfolio.db"
if os.environ.get("RENDER"):
    DB_PATH = "/opt/render/project/src/portfolio.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Portfolio(Base):
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String, nullable=True)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, index=True)
    ticker = Column(String, index=True)
    trade_type = Column(String)
    quantity = Column(Float)
    price = Column(Float)
    manual_current_price = Column(Float, nullable=True)
    timestamp = Column(DateTime)

def init_db():
    Base.metadata.create_all(bind=engine)
