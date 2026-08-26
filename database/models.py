import datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from database.base import Base

# ==========================================
# 1. HỆ THỐNG USER & LỊCH SỬ CHAT RAG
# ==========================================

class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_content_manager = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    token_version = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )

    sessions = relationship("ChatSessionModel", back_populates="user", cascade="all, delete-orphan")
    favorites = relationship("FavoriteModel", back_populates="user", cascade="all, delete-orphan")


class RateLimitBucketModel(Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        CheckConstraint(
            "request_count > 0",
            name="ck_rate_limit_buckets_request_count_positive",
        ),
    )

    scope = Column(String(64), primary_key=True)
    identifier_hash = Column(String(64), primary_key=True)
    request_count = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class ChatSessionModel(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index(
            "ix_chat_sessions_user_id_id",
            "user_id",
            "id",
        ),
        CheckConstraint(
            "next_position >= 0",
            name="ck_chat_sessions_next_position_nonnegative",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    title = Column(
        String,
        nullable=False,
        default="Cuộc trò chuyện mới",
        server_default="Cuộc trò chuyện mới",
    )
    next_position = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )

    user = relationship("UserModel", back_populates="sessions")
    messages = relationship(
        "MessageModel",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MessageModel(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "position",
            name="uq_messages_session_position",
        ),
        UniqueConstraint(
            "session_id",
            "turn_id",
            "role",
            name="uq_messages_session_turn_role",
        ),
        UniqueConstraint(
            "client_request_id",
            name="uq_messages_client_request_id",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_messages_position_nonnegative",
        ),
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_messages_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'error')",
            name="ck_messages_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(String(36), nullable=False, index=True)
    client_request_id = Column(String(36), nullable=True)
    position = Column(Integer, nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    district_filter = Column(String, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )

    session = relationship("ChatSessionModel", back_populates="messages")


# ==========================================
# 2. COURSE REGISTRY DÙNG CHUNG
# ==========================================

class CourseModel(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    domain = Column(
        String(64),
        nullable=False,
        default="political_theory",
        server_default="political_theory",
    )
    language = Column(
        String(10),
        nullable=False,
        default="vi",
        server_default="vi",
    )
    description = Column(Text, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        server_default=func.now(),
    )

    versions = relationship(
        "CourseVersionModel",
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CourseVersionModel.id",
    )


class CourseVersionModel(Base):
    __tablename__ = "course_versions"
    __table_args__ = (
        UniqueConstraint(
            "course_pk",
            "version",
            name="uq_course_versions_course_version",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PROCESSING', 'REVIEW_REQUIRED', "
            "'VALIDATED', 'ACTIVE', 'ARCHIVED')",
            name="ck_course_versions_status",
        ),
        Index(
            "ix_course_versions_course_pk_status",
            "course_pk",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    course_pk = Column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(String(32), nullable=False)
    status = Column(
        String(32),
        nullable=False,
        default="DRAFT",
        server_default="DRAFT",
    )
    vector_alias = Column(String(160), nullable=False)
    graph_namespace = Column(String(160), nullable=False)
    manifest_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        server_default=func.now(),
    )
    activated_at = Column(DateTime, nullable=True)

    course = relationship("CourseModel", back_populates="versions")


class LearnerConceptMasteryModel(Base):
    __tablename__ = "learner_concept_masteries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "course_id",
            "course_version",
            "concept_id",
            name="uq_learner_concept_mastery_scope",
        ),
        CheckConstraint(
            "mastery_probability >= 0 AND mastery_probability <= 1",
            name="ck_learner_mastery_probability",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND correct_count >= 0 "
            "AND correct_count <= attempt_count",
            name="ck_learner_mastery_counts",
        ),
        Index(
            "ix_learner_mastery_user_course_version",
            "user_id",
            "course_id",
            "course_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(String(64), nullable=False)
    course_version = Column(String(32), nullable=False)
    concept_id = Column(String(100), nullable=False)
    concept_name = Column(String(300), nullable=False)
    mastery_probability = Column(Float, nullable=False)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    correct_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_question_id = Column(String(100), nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        server_default=func.now(),
    )


class AssessmentAttemptModel(Base):
    __tablename__ = "assessment_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED')",
            name="ck_assessment_attempt_status",
        ),
        CheckConstraint(
            "mastery_before >= 0 AND mastery_before <= 1",
            name="ck_assessment_attempt_mastery_before",
        ),
        CheckConstraint(
            "mastery_after IS NULL OR "
            "(mastery_after >= 0 AND mastery_after <= 1)",
            name="ck_assessment_attempt_mastery_after",
        ),
        Index(
            "ix_assessment_attempt_user_course_version",
            "user_id",
            "course_id",
            "course_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(String(36), unique=True, nullable=False, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(String(64), nullable=False)
    course_version = Column(String(32), nullable=False)
    question_id = Column(String(100), nullable=False)
    concept_id = Column(String(100), nullable=False)
    concept_name = Column(String(300), nullable=False)
    question_snapshot = Column(JSON, nullable=False)
    status = Column(
        String(20),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    selected_option_id = Column(String(10), nullable=True)
    is_correct = Column(Boolean, nullable=True)
    mastery_before = Column(Float, nullable=False)
    mastery_after = Column(Float, nullable=True)
    feedback = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )
    completed_at = Column(DateTime, nullable=True)


class LearningPlanModel(Base):
    __tablename__ = "learning_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PROPOSED', 'ACTIVE', 'REPLACED', 'COMPLETED')",
            name="ck_learning_plan_status",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_learning_plan_revision_positive",
        ),
        CheckConstraint(
            "proposal_kind IN ('INITIAL', 'REPLAN')",
            name="ck_learning_plan_proposal_kind",
        ),
        Index(
            "ix_learning_plan_user_course_status",
            "user_id",
            "course_id",
            "course_version",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(36), unique=True, nullable=False, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(String(64), nullable=False)
    course_version = Column(String(32), nullable=False)
    title = Column(String(200), nullable=False)
    status = Column(
        String(20),
        nullable=False,
        default="PROPOSED",
        server_default="PROPOSED",
    )
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    proposal_kind = Column(
        String(20),
        nullable=False,
        default="INITIAL",
        server_default="INITIAL",
    )
    parent_plan_id = Column(String(36), nullable=True, index=True)
    trigger_event_id = Column(String(36), nullable=True, index=True)
    request_json = Column(JSON, nullable=False)
    plan_json = Column(JSON, nullable=False)
    verification_critique = Column(Text, nullable=False)
    agent_trace_json = Column(JSON, nullable=False, default=list)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        server_default=func.now(),
    )
    approved_at = Column(DateTime, nullable=True)


class LearningEventModel(Base):
    __tablename__ = "learning_events"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "correlation_id",
            name="uq_learning_event_type_correlation",
        ),
        CheckConstraint(
            "event_type IN ('MASTERY_UPDATED', 'REPLAN_REQUIRED', "
            "'PLAN_PROPOSED', 'PLAN_APPROVED')",
            name="ck_learning_event_type",
        ),
        Index(
            "ix_learning_event_user_course_created",
            "user_id",
            "course_id",
            "course_version",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(String(64), nullable=False)
    course_version = Column(String(32), nullable=False)
    event_type = Column(String(32), nullable=False)
    aggregate_type = Column(String(32), nullable=False)
    aggregate_id = Column(String(100), nullable=True)
    correlation_id = Column(String(100), nullable=True)
    payload_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        server_default=func.now(),
    )


# ==========================================
# 3. DỮ LIỆU FOOD (MÓN ĂN & QUÁN ĂN)
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
# 4. DỮ LIỆU TRAVEL (ĐỊA ĐIỂM DU LỊCH & KHÁCH SẠN)
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
# 5. DANH SÁCH YÊU THÍCH (FAVORITES)
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
