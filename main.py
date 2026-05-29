from datetime import datetime
from enum import Enum
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, or_
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship


DATABASE_URL = "sqlite:///./support_crm.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class TicketStatus(str, Enum):
    open = "Open"
    in_progress = "In Progress"
    closed = "Closed"


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String(30), unique=True, index=True, nullable=False)
    customer_name = Column(String(120), nullable=False)
    customer_email = Column(String(160), nullable=False)
    subject = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(30), default=TicketStatus.open.value, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    notes = relationship("Note", back_populates="ticket", cascade="all, delete-orphan")


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String(30), ForeignKey("tickets.ticket_id"), nullable=False)
    note_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    ticket = relationship("Ticket", back_populates="notes")


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Support CRM API",
    description="Customer Support Ticketing CRM System",
    version="1.0.0"
)

app.mount("/static", StaticFiles(directory="static"), name="static")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_ticket_id(db: Session) -> str:
    last_ticket = db.query(Ticket).order_by(Ticket.id.desc()).first()
    next_number = 1 if not last_ticket else last_ticket.id + 1
    return f"TKT-{next_number:03d}"


class TicketCreate(BaseModel):
    customer_name: str = Field(..., min_length=2, max_length=120)
    customer_email: EmailStr
    subject: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=5)


class TicketCreateResponse(BaseModel):
    ticket_id: str
    created_at: datetime


class NoteResponse(BaseModel):
    id: int
    note_text: str
    created_at: datetime

    class Config:
        from_attributes = True


class TicketListResponse(BaseModel):
    ticket_id: str
    customer_name: str
    customer_email: str
    subject: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class TicketDetailResponse(BaseModel):
    ticket_id: str
    customer_name: str
    customer_email: str
    subject: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    notes: List[NoteResponse]

    class Config:
        from_attributes = True


class TicketUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    notes: Optional[str] = None


class TicketUpdateResponse(BaseModel):
    success: bool
    updated_at: datetime


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.post("/api/tickets", response_model=TicketCreateResponse)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    ticket = Ticket(
        ticket_id=generate_ticket_id(db),
        customer_name=payload.customer_name.strip(),
        customer_email=payload.customer_email,
        subject=payload.subject.strip(),
        description=payload.description.strip(),
        status=TicketStatus.open.value
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return TicketCreateResponse(ticket_id=ticket.ticket_id, created_at=ticket.created_at)


@app.get("/api/tickets", response_model=List[TicketListResponse])
def list_tickets(
    status: Optional[TicketStatus] = Query(default=None),
    search: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    query = db.query(Ticket)

    if status:
        query = query.filter(Ticket.status == status.value)

    if search:
        keyword = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Ticket.ticket_id.ilike(keyword),
                Ticket.customer_name.ilike(keyword),
                Ticket.customer_email.ilike(keyword),
                Ticket.subject.ilike(keyword),
                Ticket.description.ilike(keyword),
            )
        )

    return query.order_by(Ticket.created_at.desc()).all()


@app.get("/api/tickets/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return ticket


@app.put("/api/tickets/{ticket_id}", response_model=TicketUpdateResponse)
def update_ticket(ticket_id: str, payload: TicketUpdate, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if payload.status:
        ticket.status = payload.status.value

    if payload.notes and payload.notes.strip():
        note = Note(ticket_id=ticket.ticket_id, note_text=payload.notes.strip())
        db.add(note)

    ticket.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(ticket)

    return TicketUpdateResponse(success=True, updated_at=ticket.updated_at)


@app.get("/health")
def health_check():
    return {"status": "ok"}
