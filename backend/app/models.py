import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base
import enum

class QueueStatus(str, enum.Enum):
    QUEUED = "queued"
    PLAYING = "playing"
    COMPLETED = "completed"
    SKIPPED = "skipped"

class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False)
    role = Column(String(20), default="user")  # 'user', 'admin'
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    queue_items = relationship("QueueItem", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")

class PriorityTier(Base):
    __tablename__ = "priority_tiers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    cost = Column(Float, nullable=False)
    priority_boost = Column(Integer, nullable=False)
    description = Column(String(255), nullable=True)

class QueueItem(Base):
    __tablename__ = "queue"

    id = Column(Integer, primary_key=True, index=True)
    song_id = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    artist = Column(String(255), nullable=False)
    duration_seconds = Column(Integer, default=180)
    thumbnail_url = Column(Text, nullable=True)
    provider = Column(String(50), default="youtube") # 'youtube', 'spotify'
    
    # Priority sorting score. Base score is timestamp based, increased by paid priority tiers.
    priority_score = Column(Float, default=0.0, index=True)
    status = Column(SQLEnum(QueueStatus), default=QueueStatus.QUEUED, index=True)
    
    added_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    paid_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="queue_items")
    transactions = relationship("Transaction", back_populates="queue_item")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    queue_id = Column(Integer, ForeignKey("queue.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    status = Column(SQLEnum(TransactionStatus), default=TransactionStatus.COMPLETED)
    payment_method = Column(String(50), default="mock_card")
    transaction_reference = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    queue_item = relationship("QueueItem", back_populates="transactions")
    user = relationship("User", back_populates="transactions")
