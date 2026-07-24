import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from database.connection import Base

# ==========================================
# 1. HỆ THỐNG USER & LỊCH SỬ CHAT RAG
# ==========================================

class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    sessions = relationship("ChatSessionModel", back_populates="user", cascade="all, delete-orphan")
    favorites = relationship("FavoriteModel", back_populates="user", cascade="all, delete-orphan")


class ChatSessionModel(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, default="Cuộc trò chuyện mới")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("UserModel", back_populates="sessions")
    messages = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan")


class MessageModel(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    district_filter = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    session = relationship("ChatSessionModel", back_populates="messages")


# ==========================================
# 2. DỮ LIỆU FOOD (MÓN ĂN & QUÁN ĂN)
# ==========================================

class FoodModel(Base):
    __tablename__ = "foods"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    category = Column(String)  # Ví dụ: Bún/Phở, Lẩu, Ăn vặt...
    description = Column(Text)
    price_range = Column(String)

    favorites = relationship("FavoriteModel", back_populates="food", cascade="all, delete-orphan")


class RestaurantModel(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    address = Column(String, nullable=False)
    district = Column(String, nullable=False, index=True)
    description = Column(Text)
    rating = Column(Float, default=0.0)
    price_range = Column(String)

    favorites = relationship("FavoriteModel", back_populates="restaurant", cascade="all, delete-orphan")


# ==========================================
# 3. DỮ LIỆU TRAVEL (ĐỊA ĐIỂM DU LỊCH & KHÁCH SẠN)
# ==========================================

class TravelPlaceModel(Base):
    __tablename__ = "travel_places"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    address = Column(String, nullable=False)
    district = Column(String, nullable=False, index=True)
    description = Column(Text)
    best_time_to_visit = Column(String)
    ticket_price = Column(String)

    favorites = relationship("FavoriteModel", back_populates="travel_place", cascade="all, delete-orphan")


class HotelModel(Base):
    __tablename__ = "hotels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    address = Column(String, nullable=False)
    district = Column(String, nullable=False, index=True)
    description = Column(Text)
    rating = Column(Float, default=0.0)
    stars = Column(Integer, default=3)

    favorites = relationship("FavoriteModel", back_populates="hotel", cascade="all, delete-orphan")


# ==========================================
# 4. DANH SÁCH YÊU THÍCH (FAVORITES)
# ==========================================

class FavoriteModel(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=True)
    travel_place_id = Column(Integer, ForeignKey("travel_places.id"), nullable=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("UserModel", back_populates="favorites")
    food = relationship("FoodModel", back_populates="favorites")
    restaurant = relationship("RestaurantModel", back_populates="favorites")
    travel_place = relationship("TravelPlaceModel", back_populates="favorites")
    hotel = relationship("HotelModel", back_populates="favorites")