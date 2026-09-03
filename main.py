import csv
import io
import os
import re
import reportlab
import xlwt
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, String, Table as SqlTable, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as PdfImage, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dochadzka.db")
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
JWT_ALG = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_NAME = os.getenv("ADMIN_NAME", "Administrátor")

engine_args = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, **engine_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

VALID_TYPES = {"Práca", "Dovolenka", "Lekár", "PN", "OČR", "Náhradné voľno", "Iné"}
VALID_STATUSES = {"approved", "rejected", "pending"}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class Base(DeclarativeBase):
    pass


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    city: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(250), default="")
    km_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


user_locations = SqlTable(
    "user_locations",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("location_id", ForeignKey("locations.id"), primary_key=True),
)


class Shift(Base):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    time_from: Mapped[str] = mapped_column(String(5))
    time_to: Mapped[str] = mapped_column(String(5))
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    deduct_break: Mapped[bool] = mapped_column(Boolean, default=True)
    location: Mapped[Location] = relationship()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    personal_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    login: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="employee")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Legacy/default location kept for backwards compatibility and as the initial selection in the app.
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"), nullable=True)
    location: Mapped[Optional[Location]] = relationship(foreign_keys=[location_id])
    locations: Mapped[list[Location]] = relationship(secondary=user_locations, lazy="selectin")


class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    type: Mapped[str] = mapped_column(String(40), default="Práca")
    time_from: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    time_to: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    deduct_break: Mapped[bool] = mapped_column(Boolean, default=True)
    km: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped[User] = relationship()
    location: Mapped[Location] = relationship()


class LoginIn(BaseModel):
    login: str
    password: str


class LocationIn(BaseModel):
    name: str
    city: str = ""
    address: str = ""
    km_enabled: bool = False


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    km_enabled: Optional[bool] = None


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    city: str
    address: str
    km_enabled: bool = False


class ShiftIn(BaseModel):
    location_id: int
    name: str
    time_from: str
    time_to: str
    break_minutes: int = 0
    deduct_break: bool = True


class ShiftUpdate(BaseModel):
    location_id: Optional[int] = None
    name: Optional[str] = None
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    break_minutes: Optional[int] = None
    deduct_break: Optional[bool] = None


class UserIn(BaseModel):
    personal_number: str
    name: str
    login: str
    password: str
    # New clients use location_ids; location_id remains accepted for backwards compatibility.
    location_ids: list[int] = Field(default_factory=list)
    location_id: Optional[int] = None
    active: bool = True


class UserUpdate(BaseModel):
    personal_number: Optional[str] = None
    name: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    location_ids: Optional[list[int]] = None
    location_id: Optional[int] = None
    active: Optional[bool] = None


class AttendanceIn(BaseModel):
    work_date: date
    location_id: int
    type: str
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    break_minutes: int = 0
    deduct_break: bool = True
    km: int = 0
    note: str = ""
    user_id: Optional[int] = None


class AttendanceUpdate(BaseModel):
    work_date: Optional[date] = None
    location_id: Optional[int] = None
    user_id: Optional[int] = None
    type: Optional[str] = None
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    break_minutes: Optional[int] = None
    deduct_break: Optional[bool] = None
    km: Optional[int] = None
    note: Optional[str] = None
    status: Optional[str] = None


class StatusIn(BaseModel):
    status: str


app = FastAPI(title="Dochádzka API", version="5.5")
origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False if "*" in origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.dirname(__file__)


def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def token_for(user: User):
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def get_current_user(
    authorization: Optional[str] = Header(None),
    session: Session = Depends(db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Chýba prihlásenie")
    token = authorization.split(" ", 1)[1]
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        uid = int(data["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Neplatný token")
    user = session.get(User, uid)
    if not user or not user.active:
        raise HTTPException(401, "Účet nie je aktívny")
    return user


def admin_only(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Len pre administrátora")
    return user


def attendance_hours(a: Attendance) -> float:
    if a.type != "Práca" or not a.time_from or not a.time_to:
        return 0.0
    try:
        fh, fm = map(int, a.time_from.split(":"))
        th, tm = map(int, a.time_to.split(":"))
        start = fh * 60 + fm
        end = th * 60 + tm
        if end < start:
            end += 24 * 60
        mins = end - start - ((a.break_minutes or 0) if a.deduct_break else 0)
        return max(0, mins / 60)
    except Exception:
        return 0.0


def validate_time(value: Optional[str], field_name: str) -> Optional[str]:
    if value in (None, ""):
        return None
    value = value.strip()
    if not TIME_RE.match(value):
        raise HTTPException(400, f"{field_name} musí byť vo formáte HH:MM")
    return value


def normalize_attendance_fields(
    item_type: str,
    time_from: Optional[str],
    time_to: Optional[str],
    break_minutes: int,
    deduct_break: bool,
):
    if item_type not in VALID_TYPES:
        raise HTTPException(400, "Neplatný typ záznamu")
    if break_minutes < 0 or break_minutes > 1440:
        raise HTTPException(400, "Prestávka musí byť medzi 0 a 1440 minútami")

    if item_type in {"Práca", "Lekár"}:
        time_from = validate_time(time_from, "Čas od")
        time_to = validate_time(time_to, "Čas do")
    else:
        time_from = None
        time_to = None

    if item_type != "Práca":
        break_minutes = 0
        deduct_break = False

    return time_from, time_to, break_minutes, bool(deduct_break)


def normalize_km(value: Optional[int], item_type: str, location: Location) -> int:
    if item_type != "Práca" or not location.km_enabled:
        return 0
    try:
        km = int(value or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Kilometre musia byť celé číslo")
    if km < 0 or km > 100000:
        raise HTTPException(400, "Kilometre musia byť medzi 0 a 100 000")
    return km


def assigned_location_ids(user: User) -> list[int]:
    ids = [loc.id for loc in (user.locations or [])]
    if not ids and user.location_id is not None:
        ids = [user.location_id]
    return list(dict.fromkeys(ids))


def validate_user_locations(session: Session, ids: list[int]) -> list[Location]:
    clean_ids = []
    for raw in ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in clean_ids:
            clean_ids.append(value)
    if not clean_ids:
        raise HTTPException(400, "Vyber aspoň jednu prevádzku")
    locs = session.scalars(select(Location).where(Location.id.in_(clean_ids))).all()
    by_id = {loc.id: loc for loc in locs}
    if len(by_id) != len(clean_ids):
        raise HTTPException(400, "Jedna alebo viac prevádzok neexistuje")
    return [by_id[x] for x in clean_ids]


def serialize_shift(x: Shift):
    return {
        "id": x.id,
        "location_id": x.location_id,
        "location_name": x.location.name if x.location else None,
        "name": x.name,
        "time_from": x.time_from,
        "time_to": x.time_to,
        "break_minutes": x.break_minutes or 0,
        "deduct_break": bool(x.deduct_break),
    }


def serialize_user(u: User):
    assigned = sorted((u.locations or []), key=lambda x: x.name.lower())
    if not assigned and u.location is not None:
        assigned = [u.location]
    return {
        "id": u.id,
        "personal_number": u.personal_number,
        "name": u.name,
        "login": u.login,
        "role": u.role,
        "active": u.active,
        "location_id": u.location_id,
        "location_name": u.location.name if u.location else (assigned[0].name if assigned else None),
        "location_ids": [x.id for x in assigned],
        "location_names": [x.name for x in assigned],
    }


def serialize_attendance(a: Attendance):
    return {
        "id": a.id,
        "work_date": a.work_date.isoformat(),
        "user_id": a.user_id,
        "personal_number": a.user.personal_number,
        "user_name": a.user.name,
        "location_id": a.location_id,
        "location_name": a.location.name,
        "type": a.type,
        "time_from": a.time_from,
        "time_to": a.time_to,
        "break_minutes": a.break_minutes,
        "deduct_break": bool(a.deduct_break),
        "km": int(a.km or 0),
        "hours": round(attendance_hours(a), 2),
        "note": a.note,
        "status": a.status,
    }


def ensure_schema_columns():
    """Add columns introduced after the first deployment without deleting existing data."""
    inspector = inspect(engine)
    migrations = {
        "locations": [("km_enabled", "BOOLEAN NOT NULL DEFAULT FALSE")],
        "shifts": [
            ("break_minutes", "INTEGER NOT NULL DEFAULT 0"),
            ("deduct_break", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ],
        "attendance": [
            ("deduct_break", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("km", "INTEGER NOT NULL DEFAULT 0"),
        ],
    }
    with engine.begin() as conn:
        for table_name, columns in migrations.items():
            existing = {c["name"] for c in inspector.get_columns(table_name)}
            for column_name, ddl in columns:
                if column_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    ensure_schema_columns()
    with SessionLocal() as session:
        admin = session.scalar(select(User).where(User.login == ADMIN_LOGIN))
        if not admin:
            admin = User(
                personal_number="ADMIN",
                name=ADMIN_NAME,
                login=ADMIN_LOGIN,
                password_hash=pwd.hash(ADMIN_PASSWORD),
                role="admin",
                active=True,
                location_id=None,
            )
            session.add(admin)
            session.commit()

        # Migrate existing single-location employee assignments into the new mapping table.
        employees = session.scalars(select(User).where(User.role == "employee")).all()
        changed = False
        for employee in employees:
            if employee.location_id is not None and not any(loc.id == employee.location_id for loc in (employee.locations or [])):
                loc = session.get(Location, employee.location_id)
                if loc is not None:
                    employee.locations.append(loc)
                    changed = True
        if changed:
            session.commit()


@app.get("/")
def root():
    return {"name": "Dochádzka API", "version": "5.5", "admin": "/admin", "docs": "/docs"}


@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(static_dir, "admin.html"))


@app.get("/brand.png")
def brand_logo():
    logo = os.path.join(static_dir, "brand.png")
    if not os.path.exists(logo):
        raise HTTPException(404, "Logo neexistuje")
    return FileResponse(logo, media_type="image/png")


@app.post("/api/auth/login")
def login(data: LoginIn, session: Session = Depends(db)):
    user = session.scalar(select(User).where(User.login == data.login.strip()))
    if not user or not user.active or not pwd.verify(data.password, user.password_hash):
        raise HTTPException(401, "Nesprávny login alebo heslo")
    return {"access_token": token_for(user), "token_type": "bearer", "user": serialize_user(user)}


@app.get("/api/me")
def me(user: User = Depends(get_current_user)):
    return serialize_user(user)


@app.get("/api/locations")
def locations(session: Session = Depends(db), user: User = Depends(get_current_user)):
    stmt = select(Location).order_by(Location.name)
    if user.role != "admin":
        ids = assigned_location_ids(user)
        if not ids:
            return []
        stmt = stmt.where(Location.id.in_(ids))
    return [LocationOut.model_validate(x).model_dump() for x in session.scalars(stmt).all()]


@app.post("/api/locations")
def create_location(data: LocationIn, session: Session = Depends(db), _: User = Depends(admin_only)):
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Názov prevádzky je povinný")
    if session.scalar(select(Location).where(Location.name == name)):
        raise HTTPException(400, "Prevádzka s týmto názvom už existuje")
    obj = Location(name=name, city=data.city.strip(), address=data.address.strip(), km_enabled=bool(data.km_enabled))
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return LocationOut.model_validate(obj).model_dump()


@app.patch("/api/locations/{location_id}")
def update_location(
    location_id: int,
    data: LocationUpdate,
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    obj = session.get(Location, location_id)
    if not obj:
        raise HTTPException(404, "Prevádzka neexistuje")

    fields = data.model_fields_set
    if "name" in fields:
        name = (data.name or "").strip()
        if not name:
            raise HTTPException(400, "Názov prevádzky je povinný")
        duplicate = session.scalar(select(Location).where(Location.name == name, Location.id != location_id))
        if duplicate:
            raise HTTPException(400, "Prevádzka s týmto názvom už existuje")
        obj.name = name
    if "city" in fields:
        obj.city = (data.city or "").strip()
    if "address" in fields:
        obj.address = (data.address or "").strip()
    if "km_enabled" in fields:
        obj.km_enabled = bool(data.km_enabled)

    session.commit()
    session.refresh(obj)
    return LocationOut.model_validate(obj).model_dump()


@app.delete("/api/locations/{location_id}")
def delete_location(
    location_id: int,
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    obj = session.get(Location, location_id)
    if not obj:
        raise HTTPException(404, "Prevádzka neexistuje")
    if session.scalar(select(Shift.id).where(Shift.location_id == location_id).limit(1)):
        raise HTTPException(409, "Prevádzka má prednastavené zmeny. Najprv ich odstráň alebo presuň.")
    if session.scalar(select(User.id).where(User.location_id == location_id).limit(1)):
        raise HTTPException(409, "Prevádzku používa zamestnanec. Najprv zmeň jeho prevádzky.")
    if session.execute(select(user_locations.c.user_id).where(user_locations.c.location_id == location_id).limit(1)).first():
        raise HTTPException(409, "Prevádzku používa zamestnanec. Najprv zmeň jeho prevádzky.")
    if session.scalar(select(Attendance.id).where(Attendance.location_id == location_id).limit(1)):
        raise HTTPException(409, "Prevádzka je použitá v dochádzke. Najprv odstráň alebo presuň tieto záznamy.")
    session.delete(obj)
    session.commit()
    return {"ok": True}


@app.get("/api/shifts")
def shifts(
    location_id: Optional[int] = Query(None),
    session: Session = Depends(db),
    user: User = Depends(get_current_user),
):
    stmt = select(Shift).order_by(Shift.location_id, Shift.time_from, Shift.name)
    if user.role != "admin":
        ids = assigned_location_ids(user)
        if not ids:
            return []
        if location_id:
            if location_id not in ids:
                raise HTTPException(403, "Táto prevádzka ti nie je priradená")
            stmt = stmt.where(Shift.location_id == location_id)
        else:
            stmt = stmt.where(Shift.location_id.in_(ids))
    elif location_id:
        stmt = stmt.where(Shift.location_id == location_id)
    return [serialize_shift(x) for x in session.scalars(stmt).all()]


@app.post("/api/shifts")
def create_shift(data: ShiftIn, session: Session = Depends(db), _: User = Depends(admin_only)):
    location = session.get(Location, data.location_id)
    if not location:
        raise HTTPException(400, "Prevádzka neexistuje")
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Názov zmeny je povinný")
    time_from = validate_time(data.time_from, "Čas od")
    time_to = validate_time(data.time_to, "Čas do")
    if time_from is None or time_to is None:
        raise HTTPException(400, "Čas od a čas do sú povinné")
    if data.break_minutes < 0 or data.break_minutes > 1440:
        raise HTTPException(400, "Prestávka musí byť medzi 0 a 1440 minútami")
    duplicate = session.scalar(
        select(Shift).where(Shift.location_id == data.location_id, Shift.name == name)
    )
    if duplicate:
        raise HTTPException(400, "Zmena s týmto názvom už v prevádzke existuje")
    obj = Shift(
        location_id=data.location_id,
        name=name,
        time_from=time_from,
        time_to=time_to,
        break_minutes=data.break_minutes,
        deduct_break=data.deduct_break,
    )
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return serialize_shift(obj)


@app.patch("/api/shifts/{shift_id}")
def update_shift(
    shift_id: int,
    data: ShiftUpdate,
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    obj = session.get(Shift, shift_id)
    if not obj:
        raise HTTPException(404, "Zmena neexistuje")
    fields = data.model_fields_set
    target_location_id = obj.location_id
    if "location_id" in fields:
        if data.location_id is None or not session.get(Location, data.location_id):
            raise HTTPException(400, "Prevádzka neexistuje")
        target_location_id = data.location_id
    target_name = obj.name
    if "name" in fields:
        target_name = (data.name or "").strip()
        if not target_name:
            raise HTTPException(400, "Názov zmeny je povinný")
    duplicate = session.scalar(
        select(Shift).where(
            Shift.location_id == target_location_id,
            Shift.name == target_name,
            Shift.id != shift_id,
        )
    )
    if duplicate:
        raise HTTPException(400, "Zmena s týmto názvom už v prevádzke existuje")
    obj.location_id = target_location_id
    obj.name = target_name
    if "time_from" in fields:
        value = validate_time(data.time_from, "Čas od")
        if value is None:
            raise HTTPException(400, "Čas od je povinný")
        obj.time_from = value
    if "time_to" in fields:
        value = validate_time(data.time_to, "Čas do")
        if value is None:
            raise HTTPException(400, "Čas do je povinný")
        obj.time_to = value
    if "break_minutes" in fields:
        value = 0 if data.break_minutes is None else data.break_minutes
        if value < 0 or value > 1440:
            raise HTTPException(400, "Prestávka musí byť medzi 0 a 1440 minútami")
        obj.break_minutes = value
    if "deduct_break" in fields:
        obj.deduct_break = True if data.deduct_break is None else data.deduct_break
    session.commit()
    session.refresh(obj)
    return serialize_shift(obj)


@app.delete("/api/shifts/{shift_id}")
def delete_shift(shift_id: int, session: Session = Depends(db), _: User = Depends(admin_only)):
    obj = session.get(Shift, shift_id)
    if not obj:
        raise HTTPException(404, "Zmena neexistuje")
    session.delete(obj)
    session.commit()
    return {"ok": True}


@app.get("/api/users")
def users(session: Session = Depends(db), _: User = Depends(admin_only)):
    items = session.scalars(select(User).where(User.role == "employee").order_by(User.name)).all()
    return [serialize_user(x) for x in items]


@app.post("/api/users")
def create_user(data: UserIn, session: Session = Depends(db), _: User = Depends(admin_only)):
    personal_number = data.personal_number.strip()
    name = data.name.strip()
    login_value = data.login.strip()
    if not personal_number or not name or not login_value or not data.password:
        raise HTTPException(400, "Osobné číslo, meno, login a heslo sú povinné")
    if session.scalar(select(User).where(User.login == login_value)):
        raise HTTPException(400, "Login už existuje")
    if session.scalar(select(User).where(User.personal_number == personal_number)):
        raise HTTPException(400, "Osobné číslo už existuje")
    requested_ids = data.location_ids or ([data.location_id] if data.location_id is not None else [])
    locs = validate_user_locations(session, requested_ids)
    obj = User(
        personal_number=personal_number,
        name=name,
        login=login_value,
        password_hash=pwd.hash(data.password),
        role="employee",
        active=data.active,
        location_id=locs[0].id,
    )
    obj.locations = locs
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return serialize_user(obj)


@app.patch("/api/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    obj = session.get(User, user_id)
    if not obj or obj.role != "employee":
        raise HTTPException(404, "Zamestnanec neexistuje")

    fields = data.model_fields_set
    if "personal_number" in fields:
        value = (data.personal_number or "").strip()
        if not value:
            raise HTTPException(400, "Osobné číslo je povinné")
        duplicate = session.scalar(select(User).where(User.personal_number == value, User.id != user_id))
        if duplicate:
            raise HTTPException(400, "Osobné číslo už existuje")
        obj.personal_number = value
    if "name" in fields:
        value = (data.name or "").strip()
        if not value:
            raise HTTPException(400, "Meno je povinné")
        obj.name = value
    if "login" in fields:
        value = (data.login or "").strip()
        if not value:
            raise HTTPException(400, "Login je povinný")
        duplicate = session.scalar(select(User).where(User.login == value, User.id != user_id))
        if duplicate:
            raise HTTPException(400, "Login už existuje")
        obj.login = value
    if "location_ids" in fields or "location_id" in fields:
        requested_ids = (data.location_ids or []) if "location_ids" in fields else []
        if not requested_ids and "location_id" in fields and data.location_id is not None:
            requested_ids = [data.location_id]
        locs = validate_user_locations(session, requested_ids)
        obj.locations = locs
        if data.location_id is not None and any(x.id == data.location_id for x in locs):
            obj.location_id = data.location_id
        elif obj.location_id not in [x.id for x in locs]:
            obj.location_id = locs[0].id
    if "active" in fields and data.active is not None:
        obj.active = data.active
    if "password" in fields and data.password:
        obj.password_hash = pwd.hash(data.password)

    session.commit()
    session.refresh(obj)
    return serialize_user(obj)


@app.patch("/api/users/{user_id}/active")
def toggle_user(user_id: int, session: Session = Depends(db), _: User = Depends(admin_only)):
    u = session.get(User, user_id)
    if not u or u.role != "employee":
        raise HTTPException(404, "Používateľ neexistuje")
    u.active = not u.active
    session.commit()
    session.refresh(u)
    return serialize_user(u)


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, session: Session = Depends(db), _: User = Depends(admin_only)):
    obj = session.get(User, user_id)
    if not obj or obj.role != "employee":
        raise HTTPException(404, "Zamestnanec neexistuje")
    if session.scalar(select(Attendance.id).where(Attendance.user_id == user_id).limit(1)):
        raise HTTPException(409, "Zamestnanec má dochádzku. Najprv odstráň jeho dochádzkové záznamy alebo ho iba deaktivuj.")
    session.delete(obj)
    session.commit()
    return {"ok": True}


@app.get("/api/attendance")
def get_attendance(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    session: Session = Depends(db),
    user: User = Depends(get_current_user),
):
    stmt = select(Attendance).order_by(Attendance.work_date.desc(), Attendance.id.desc())
    if user.role != "admin":
        stmt = stmt.where(Attendance.user_id == user.id)
    elif user_id:
        stmt = stmt.where(Attendance.user_id == user_id)
    if location_id:
        stmt = stmt.where(Attendance.location_id == location_id)
    if date_from:
        stmt = stmt.where(Attendance.work_date >= date_from)
    if date_to:
        stmt = stmt.where(Attendance.work_date <= date_to)
    return [serialize_attendance(a) for a in session.scalars(stmt).all()]


@app.post("/api/attendance")
def create_attendance(
    data: AttendanceIn,
    session: Session = Depends(db),
    user: User = Depends(get_current_user),
):
    target_user_id = data.user_id if user.role == "admin" and data.user_id else user.id
    target_user = session.get(User, target_user_id)
    if not target_user or target_user.role != "employee":
        raise HTTPException(400, "Zamestnanec neexistuje")
    location = session.get(Location, data.location_id)
    if not location:
        raise HTTPException(400, "Prevádzka neexistuje")
    if user.role != "admin" and data.location_id not in assigned_location_ids(user):
        raise HTTPException(403, "Táto prevádzka ti nie je priradená")

    time_from, time_to, break_minutes, deduct_break = normalize_attendance_fields(
        data.type, data.time_from, data.time_to, data.break_minutes, data.deduct_break
    )
    km = normalize_km(data.km, data.type, location)
    obj = Attendance(
        work_date=data.work_date,
        user_id=target_user_id,
        location_id=data.location_id,
        type=data.type,
        time_from=time_from,
        time_to=time_to,
        break_minutes=break_minutes,
        deduct_break=deduct_break,
        km=km,
        note=data.note.strip(),
        status="approved" if user.role == "admin" else "pending",
    )
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return serialize_attendance(obj)


@app.patch("/api/attendance/{attendance_id}")
def update_attendance(
    attendance_id: int,
    data: AttendanceUpdate,
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    obj = session.get(Attendance, attendance_id)
    if not obj:
        raise HTTPException(404, "Záznam neexistuje")

    fields = data.model_fields_set
    if "work_date" in fields:
        if data.work_date is None:
            raise HTTPException(400, "Dátum je povinný")
        obj.work_date = data.work_date
    if "user_id" in fields:
        target = session.get(User, data.user_id) if data.user_id is not None else None
        if not target or target.role != "employee":
            raise HTTPException(400, "Zamestnanec neexistuje")
        obj.user_id = data.user_id
    if "location_id" in fields:
        if data.location_id is None or not session.get(Location, data.location_id):
            raise HTTPException(400, "Prevádzka neexistuje")
        obj.location_id = data.location_id
    if "type" in fields:
        if data.type is None or data.type not in VALID_TYPES:
            raise HTTPException(400, "Neplatný typ záznamu")
        obj.type = data.type
    if "status" in fields:
        if data.status is None or data.status not in VALID_STATUSES:
            raise HTTPException(400, "Neplatný stav")
        obj.status = data.status
    if "note" in fields:
        obj.note = (data.note or "").strip()

    raw_from = data.time_from if "time_from" in fields else obj.time_from
    raw_to = data.time_to if "time_to" in fields else obj.time_to
    raw_break = data.break_minutes if "break_minutes" in fields and data.break_minutes is not None else obj.break_minutes
    raw_deduct = data.deduct_break if "deduct_break" in fields and data.deduct_break is not None else obj.deduct_break
    obj.time_from, obj.time_to, obj.break_minutes, obj.deduct_break = normalize_attendance_fields(
        obj.type, raw_from, raw_to, raw_break, raw_deduct
    )
    location = session.get(Location, obj.location_id)
    obj.km = normalize_km(data.km if "km" in fields else obj.km, obj.type, location)

    session.commit()
    session.refresh(obj)
    return serialize_attendance(obj)


@app.patch("/api/attendance/{attendance_id}/status")
def set_status(
    attendance_id: int,
    data: StatusIn,
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    if data.status not in VALID_STATUSES:
        raise HTTPException(400, "Neplatný stav")
    obj = session.get(Attendance, attendance_id)
    if not obj:
        raise HTTPException(404, "Záznam neexistuje")
    obj.status = data.status
    session.commit()
    session.refresh(obj)
    return serialize_attendance(obj)


@app.delete("/api/attendance/{attendance_id}")
def delete_attendance(
    attendance_id: int,
    session: Session = Depends(db),
    user: User = Depends(get_current_user),
):
    obj = session.get(Attendance, attendance_id)
    if not obj:
        raise HTTPException(404, "Záznam neexistuje")
    if user.role != "admin" and not (obj.user_id == user.id and obj.status == "pending"):
        raise HTTPException(403, "Záznam nemôžeš zmazať")
    session.delete(obj)
    session.commit()
    return {"ok": True}



STATUS_SK = {
    "approved": "Schválené",
    "pending": "Čaká na schválenie",
    "rejected": "Zamietnuté",
}


def filtered_attendance_rows(
    session: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user_id: Optional[int] = None,
    location_id: Optional[int] = None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "Dátum Od nemôže byť neskôr ako Dátum Do")
    stmt = select(Attendance).order_by(Attendance.work_date, Attendance.user_id, Attendance.id)
    if date_from:
        stmt = stmt.where(Attendance.work_date >= date_from)
    if date_to:
        stmt = stmt.where(Attendance.work_date <= date_to)
    if user_id:
        stmt = stmt.where(Attendance.user_id == user_id)
    if location_id:
        stmt = stmt.where(Attendance.location_id == location_id)
    return session.scalars(stmt).all()


def export_period_text(date_from: Optional[date], date_to: Optional[date]) -> str:
    def f(d: Optional[date]) -> str:
        return d.strftime("%d.%m.%Y") if d else "bez obmedzenia"
    return f"{f(date_from)} - {f(date_to)}"


def ensure_pdf_fonts():
    if "Vera" in pdfmetrics.getRegisteredFontNames():
        return
    fonts_dir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    pdfmetrics.registerFont(TTFont("Vera", os.path.join(fonts_dir, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("VeraBd", os.path.join(fonts_dir, "VeraBd.ttf")))


def pdf_logo(max_height=13 * mm):
    logo_path = os.path.join(static_dir, "brand.png")
    if not os.path.exists(logo_path):
        return None
    img = PdfImage(logo_path)
    ratio = img.imageWidth / max(1, img.imageHeight)
    img.drawHeight = max_height
    img.drawWidth = max_height * ratio
    return img


def pdf_footer(canvas, doc):
    ensure_pdf_fonts()
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D9E3D8"))
    canvas.line(doc.leftMargin, 8 * mm, doc.pagesize[0] - doc.rightMargin, 8 * mm)
    canvas.setFont("Vera", 7)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(doc.leftMargin, 4.5 * mm, "MIELL Dochádzka")
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 4.5 * mm, f"Strana {doc.page}")
    canvas.restoreState()


def pdf_paragraph(value, style):
    text_value = str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(text_value, style)


def build_admin_pdf(
    rows,
    date_from: Optional[date],
    date_to: Optional[date],
    user_label: str,
    location_label: str,
):
    ensure_pdf_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=13 * mm,
        title="Export dochádzky",
        author="MIELL Quality",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleVera", parent=styles["Title"], fontName="VeraBd", fontSize=16, leading=19, textColor=colors.HexColor("#172033"), alignment=TA_LEFT)
    small = ParagraphStyle("SmallVera", parent=styles["BodyText"], fontName="Vera", fontSize=6.4, leading=8, textColor=colors.HexColor("#172033"))
    small_center = ParagraphStyle("SmallCenter", parent=small, alignment=TA_CENTER)
    meta = ParagraphStyle("MetaVera", parent=styles["BodyText"], fontName="Vera", fontSize=8, leading=10, textColor=colors.HexColor("#667085"))
    summary = ParagraphStyle("SummaryVera", parent=styles["BodyText"], fontName="VeraBd", fontSize=9, leading=11, textColor=colors.HexColor("#172033"))

    story = []
    logo = pdf_logo()
    if logo:
        header = Table([[logo, Paragraph("Export dochádzky", title_style)]], colWidths=[60 * mm, 210 * mm])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(header)
    else:
        story.append(Paragraph("Export dochádzky", title_style))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"Obdobie: <b>{export_period_text(date_from, date_to)}</b> &nbsp;&nbsp; Zamestnanec: <b>{user_label}</b> &nbsp;&nbsp; Prevádzka: <b>{location_label}</b>",
        meta,
    ))
    story.append(Spacer(1, 3 * mm))

    headers = ["Dátum", "Os. číslo", "Zamestnanec", "Prevádzka", "Typ", "Od", "Do", "Prestávka", "Odr.", "Hodiny", "KM", "Stav", "Poznámka"]
    data = [[pdf_paragraph(h, small_center) for h in headers]]
    for a in rows:
        data.append([
            pdf_paragraph(a.work_date.strftime("%d.%m.%Y"), small_center),
            pdf_paragraph(a.user.personal_number, small),
            pdf_paragraph(a.user.name, small),
            pdf_paragraph(a.location.name, small),
            pdf_paragraph(a.type, small),
            pdf_paragraph(a.time_from or "", small_center),
            pdf_paragraph(a.time_to or "", small_center),
            pdf_paragraph(f"{a.break_minutes or 0} min", small_center),
            pdf_paragraph("Áno" if a.deduct_break else "Nie", small_center),
            pdf_paragraph(f"{attendance_hours(a):.2f}", small_center),
            pdf_paragraph(str(int(a.km or 0)) if a.km else "", small_center),
            pdf_paragraph(STATUS_SK.get(a.status, a.status), small),
            pdf_paragraph(a.note or "", small),
        ])
    col_widths = [18, 19, 29, 26, 20, 13, 13, 17, 12, 14, 14, 25, 41]
    table = LongTable(data, colWidths=[x * mm for x in col_widths], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#348C2E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "VeraBd"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E3D8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    approved_hours = sum(attendance_hours(a) for a in rows if a.status == "approved")
    all_hours = sum(attendance_hours(a) for a in rows)
    total_km = sum(int(a.km or 0) for a in rows)
    story.append(Paragraph(f"Počet záznamov: {len(rows)} &nbsp;&nbsp; | &nbsp;&nbsp; Schválené pracovné hodiny: {approved_hours:.2f} h &nbsp;&nbsp; | &nbsp;&nbsp; Evidované pracovné hodiny spolu: {all_hours:.2f} h &nbsp;&nbsp; | &nbsp;&nbsp; KM spolu: {total_km}", summary))
    doc.build(story, onFirstPage=pdf_footer, onLaterPages=pdf_footer)
    return buf.getvalue()


def build_employee_pdf(user: User, rows, date_from: date, date_to: date):
    ensure_pdf_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title=f"Dochádzka - {user.name}",
        author="MIELL Quality",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("EmpTitle", parent=styles["Title"], fontName="VeraBd", fontSize=16, leading=19, textColor=colors.HexColor("#172033"), alignment=TA_LEFT)
    body = ParagraphStyle("EmpBody", parent=styles["BodyText"], fontName="Vera", fontSize=8.2, leading=10.5, textColor=colors.HexColor("#172033"))
    small = ParagraphStyle("EmpSmall", parent=body, fontSize=7.2, leading=9)
    small_center = ParagraphStyle("EmpSmallCenter", parent=small, alignment=TA_CENTER)
    strong = ParagraphStyle("EmpStrong", parent=body, fontName="VeraBd", fontSize=9.2, leading=11)

    story = []
    logo = pdf_logo(15 * mm)
    if logo:
        header = Table([[logo, Paragraph("Mesačná dochádzka", title_style)]], colWidths=[60 * mm, 115 * mm])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(header)
    else:
        story.append(Paragraph("Mesačná dochádzka", title_style))
    story.append(Spacer(1, 4 * mm))

    info = [
        [Paragraph("Zamestnanec", strong), Paragraph(user.name, body)],
        [Paragraph("Osobné číslo", strong), Paragraph(user.personal_number, body)],
        [Paragraph("Priradené prevádzky", strong), Paragraph(", ".join(x.name for x in sorted((user.locations or []), key=lambda x: x.name.lower())) or (user.location.name if user.location else "-"), body)],
        [Paragraph("Obdobie", strong), Paragraph(export_period_text(date_from, date_to), body)],
    ]
    info_table = Table(info, colWidths=[38 * mm, 137 * mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F0F7EF")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E3D8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5 * mm))

    approved_hours = sum(attendance_hours(a) for a in rows if a.status == "approved")
    pending_count = sum(1 for a in rows if a.status == "pending")
    total_km = sum(int(a.km or 0) for a in rows)
    summary_table = Table([
        [Paragraph("Schválené hodiny", small), Paragraph("KM spolu", small), Paragraph("Čakajúce záznamy", small), Paragraph("Záznamy spolu", small)],
        [Paragraph(f"{approved_hours:.2f} h", strong), Paragraph(str(total_km), strong), Paragraph(str(pending_count), strong), Paragraph(str(len(rows)), strong)],
    ], colWidths=[43.5 * mm, 43.5 * mm, 43.5 * mm, 43.5 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAF7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E3D8")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 5 * mm))

    headers = ["Dátum", "Typ", "Čas", "Prestávka", "Hodiny", "KM", "Stav", "Poznámka"]
    data = [[pdf_paragraph(h, small_center) for h in headers]]
    for a in rows:
        time_text = f"{a.time_from or '-'} - {a.time_to or '-'}" if a.time_from or a.time_to else "-"
        br = f"{a.break_minutes or 0} min" if a.type == "Práca" else "-"
        if a.type == "Práca" and a.break_minutes:
            br += " (odr.)" if a.deduct_break else " (platená)"
        data.append([
            pdf_paragraph(a.work_date.strftime("%d.%m.%Y"), small_center),
            pdf_paragraph(a.type, small),
            pdf_paragraph(time_text, small_center),
            pdf_paragraph(br, small_center),
            pdf_paragraph(f"{attendance_hours(a):.2f}", small_center),
            pdf_paragraph(str(int(a.km or 0)) if a.km else "", small_center),
            pdf_paragraph(STATUS_SK.get(a.status, a.status), small),
            pdf_paragraph(a.note or "", small),
        ])
    table = LongTable(data, colWidths=[21 * mm, 21 * mm, 28 * mm, 25 * mm, 17 * mm, 15 * mm, 24 * mm, 35 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#348C2E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "VeraBd"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E3D8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF7")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    doc.build(story, onFirstPage=pdf_footer, onLaterPages=pdf_footer)
    return buf.getvalue()


def build_admin_xls(
    rows,
    date_from: Optional[date],
    date_to: Optional[date],
    user_label: str,
    location_label: str,
):
    if len(rows) > 65000:
        raise HTTPException(400, "Export XLS podporuje najviac 65 000 záznamov naraz. Zúž obdobie alebo filter.")
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Dochádzka", cell_overwrite_ok=True)
    title_style = xlwt.easyxf("font: bold on, height 320; align: vert centre;")
    label_style = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour ice_blue;")
    header_style = xlwt.easyxf("font: bold on, colour white; pattern: pattern solid, fore_colour green; align: horiz center, vert centre; borders: bottom thin, left thin, right thin, top thin;")
    cell_style = xlwt.easyxf("align: vert top; borders: bottom thin, left thin, right thin, top thin;")
    center_style = xlwt.easyxf("align: horiz center, vert top; borders: bottom thin, left thin, right thin, top thin;")
    hours_style = xlwt.easyxf("align: horiz right, vert top; borders: bottom thin, left thin, right thin, top thin;", num_format_str="0.00")
    summary_style = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour light_green;")

    ws.write_merge(0, 0, 0, 5, "MIELL Dochádzka - Export", title_style)
    ws.write(2, 0, "Obdobie", label_style); ws.write(2, 1, export_period_text(date_from, date_to))
    ws.write(3, 0, "Zamestnanec", label_style); ws.write(3, 1, user_label)
    ws.write(4, 0, "Prevádzka", label_style); ws.write(4, 1, location_label)

    headers = ["Dátum", "Osobné číslo", "Zamestnanec", "Prevádzka", "Typ", "Od", "Do", "Prestávka min", "Prestávka odrátaná", "Odpracované hodiny", "KM", "Stav", "Poznámka"]
    header_row = 6
    for c, h in enumerate(headers):
        ws.write(header_row, c, h, header_style)

    for r, a in enumerate(rows, start=header_row + 1):
        values = [
            a.work_date.strftime("%d.%m.%Y"), a.user.personal_number, a.user.name,
            a.location.name, a.type, a.time_from or "", a.time_to or "",
            int(a.break_minutes or 0), "Áno" if a.deduct_break else "Nie",
            attendance_hours(a), int(a.km or 0), STATUS_SK.get(a.status, a.status), a.note or "",
        ]
        for c, value in enumerate(values):
            if c in {9, 10}:
                ws.write(r, c, value, hours_style)
            elif c in {0, 5, 6, 7, 8}:
                ws.write(r, c, value, center_style)
            else:
                ws.write(r, c, value, cell_style)

    end_row = header_row + 1 + len(rows) + 1
    approved_hours = sum(attendance_hours(a) for a in rows if a.status == "approved")
    all_hours = sum(attendance_hours(a) for a in rows)
    ws.write(end_row, 0, "Súhrn", summary_style)
    ws.write(end_row, 1, f"Počet záznamov: {len(rows)}", summary_style)
    ws.write(end_row, 2, f"Schválené hodiny: {approved_hours:.2f}", summary_style)
    ws.write(end_row, 3, f"Evidované hodiny spolu: {all_hours:.2f}", summary_style)
    ws.write(end_row, 4, f"KM spolu: {sum(int(a.km or 0) for a in rows)}", summary_style)

    widths = [13, 16, 24, 22, 18, 9, 9, 15, 20, 18, 10, 22, 42]
    for i, w in enumerate(widths):
        ws.col(i).width = min(255, w) * 256
    ws.panes_frozen = True
    ws.horz_split_pos = header_row + 1

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def resolve_filter_labels(session: Session, user_id: Optional[int], location_id: Optional[int]):
    user_label = "Všetci"
    location_label = "Všetky"
    if user_id:
        u = session.get(User, user_id)
        user_label = u.name if u else f"ID {user_id}"
    if location_id:
        loc = session.get(Location, location_id)
        location_label = loc.name if loc else f"ID {location_id}"
    return user_label, location_label


def employee_export_token(user: User, date_from: date, date_to: date) -> str:
    payload = {
        "sub": str(user.id),
        "scope": "attendance_pdf",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "exp": datetime.utcnow() + timedelta(minutes=5),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


@app.get("/api/my/export-link")
def my_export_link(
    date_from: date = Query(...),
    date_to: date = Query(...),
    user: User = Depends(get_current_user),
):
    if date_from > date_to:
        raise HTTPException(400, "Dátum Od nemôže byť neskôr ako Dátum Do")
    if (date_to - date_from).days > 370:
        raise HTTPException(400, "PDF je možné vytvoriť najviac za obdobie 371 dní")
    token = employee_export_token(user, date_from, date_to)
    return {"url": f"/api/my-attendance.pdf?download_token={token}", "expires_in_seconds": 300}


@app.get("/api/my-attendance.pdf")
def my_attendance_pdf(
    download_token: str = Query(...),
    session: Session = Depends(db),
):
    try:
        data = jwt.decode(download_token, JWT_SECRET, algorithms=[JWT_ALG])
        if data.get("scope") != "attendance_pdf":
            raise ValueError("scope")
        uid = int(data["sub"])
        date_from = date.fromisoformat(data["date_from"])
        date_to = date.fromisoformat(data["date_to"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Odkaz na PDF je neplatný alebo vypršal")
    user = session.get(User, uid)
    if not user or not user.active:
        raise HTTPException(401, "Účet nie je aktívny")
    rows = filtered_attendance_rows(session, date_from, date_to, user_id=user.id)
    payload = build_employee_pdf(user, rows, date_from, date_to)
    filename = f"dochadzka_{user.personal_number}_{date_from.isoformat()}_{date_to.isoformat()}.pdf"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export.pdf")
def export_pdf(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    rows = filtered_attendance_rows(session, date_from, date_to, user_id, location_id)
    user_label, location_label = resolve_filter_labels(session, user_id, location_id)
    payload = build_admin_pdf(rows, date_from, date_to, user_label, location_label)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="dochadzka_export.pdf"'},
    )


@app.get("/api/export.xls")
def export_xls(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    rows = filtered_attendance_rows(session, date_from, date_to, user_id, location_id)
    user_label, location_label = resolve_filter_labels(session, user_id, location_id)
    payload = build_admin_xls(rows, date_from, date_to, user_label, location_label)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": 'attachment; filename="dochadzka_export.xls"'},
    )


@app.get("/api/export.csv")
def export_csv(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    rows = filtered_attendance_rows(session, date_from, date_to, user_id, location_id)

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Dátum", "Osobné číslo", "Zamestnanec", "Prevádzka", "Typ",
        "Od", "Do", "Prestávka min", "Prestávka odrátaná", "Odpracované hodiny", "KM", "Stav", "Poznámka"
    ])
    for a in rows:
        writer.writerow([
            a.work_date.isoformat(),
            a.user.personal_number,
            a.user.name,
            a.location.name,
            a.type,
            a.time_from or "",
            a.time_to or "",
            a.break_minutes or 0,
            "Áno" if a.deduct_break else "Nie",
            f"{attendance_hours(a):.2f}",
            int(a.km or 0),
            a.status,
            a.note or "",
        ])
    payload = output.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dochadzka_export.csv"'},
    )
