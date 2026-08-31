import csv
import io
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

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


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    personal_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    login: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="employee")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"), nullable=True)
    location: Mapped[Optional[Location]] = relationship()


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


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    city: str
    address: str


class UserIn(BaseModel):
    personal_number: str
    name: str
    login: str
    password: str
    location_id: int
    active: bool = True


class UserUpdate(BaseModel):
    personal_number: Optional[str] = None
    name: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    location_id: Optional[int] = None
    active: Optional[bool] = None


class AttendanceIn(BaseModel):
    work_date: date
    location_id: int
    type: str
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    break_minutes: int = 0
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
    note: Optional[str] = None
    status: Optional[str] = None


class StatusIn(BaseModel):
    status: str


app = FastAPI(title="Dochádzka API", version="4.0")
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
        mins = (th * 60 + tm) - (fh * 60 + fm) - (a.break_minutes or 0)
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

    return time_from, time_to, break_minutes


def serialize_user(u: User):
    return {
        "id": u.id,
        "personal_number": u.personal_number,
        "name": u.name,
        "login": u.login,
        "role": u.role,
        "active": u.active,
        "location_id": u.location_id,
        "location_name": u.location.name if u.location else None,
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
        "hours": round(attendance_hours(a), 2),
        "note": a.note,
        "status": a.status,
    }


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
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


@app.get("/")
def root():
    return {"name": "Dochádzka API", "version": "4.0", "admin": "/admin", "docs": "/docs"}


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
    return [
        LocationOut.model_validate(x).model_dump()
        for x in session.scalars(select(Location).order_by(Location.name)).all()
    ]


@app.post("/api/locations")
def create_location(data: LocationIn, session: Session = Depends(db), _: User = Depends(admin_only)):
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Názov prevádzky je povinný")
    if session.scalar(select(Location).where(Location.name == name)):
        raise HTTPException(400, "Prevádzka s týmto názvom už existuje")
    obj = Location(name=name, city=data.city.strip(), address=data.address.strip())
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
    if session.scalar(select(User.id).where(User.location_id == location_id).limit(1)):
        raise HTTPException(409, "Prevádzku používa zamestnanec. Najprv ho presuň na inú prevádzku.")
    if session.scalar(select(Attendance.id).where(Attendance.location_id == location_id).limit(1)):
        raise HTTPException(409, "Prevádzka je použitá v dochádzke. Najprv odstráň alebo presuň tieto záznamy.")
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
    if not session.get(Location, data.location_id):
        raise HTTPException(400, "Prevádzka neexistuje")
    obj = User(
        personal_number=personal_number,
        name=name,
        login=login_value,
        password_hash=pwd.hash(data.password),
        role="employee",
        active=data.active,
        location_id=data.location_id,
    )
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
    if "location_id" in fields:
        if data.location_id is None or not session.get(Location, data.location_id):
            raise HTTPException(400, "Prevádzka neexistuje")
        obj.location_id = data.location_id
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
    if not session.get(Location, data.location_id):
        raise HTTPException(400, "Prevádzka neexistuje")

    time_from, time_to, break_minutes = normalize_attendance_fields(
        data.type, data.time_from, data.time_to, data.break_minutes
    )
    obj = Attendance(
        work_date=data.work_date,
        user_id=target_user_id,
        location_id=data.location_id,
        type=data.type,
        time_from=time_from,
        time_to=time_to,
        break_minutes=break_minutes,
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
    obj.time_from, obj.time_to, obj.break_minutes = normalize_attendance_fields(
        obj.type, raw_from, raw_to, raw_break
    )

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


@app.get("/api/export.csv")
def export_csv(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    session: Session = Depends(db),
    _: User = Depends(admin_only),
):
    stmt = select(Attendance).order_by(Attendance.work_date, Attendance.user_id)
    if date_from:
        stmt = stmt.where(Attendance.work_date >= date_from)
    if date_to:
        stmt = stmt.where(Attendance.work_date <= date_to)
    if user_id:
        stmt = stmt.where(Attendance.user_id == user_id)
    if location_id:
        stmt = stmt.where(Attendance.location_id == location_id)
    rows = session.scalars(stmt).all()

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Dátum", "Osobné číslo", "Zamestnanec", "Prevádzka", "Typ",
        "Od", "Do", "Prestávka min", "Odpracované hodiny", "Stav", "Poznámka"
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
            f"{attendance_hours(a):.2f}",
            a.status,
            a.note or "",
        ])
    payload = output.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dochadzka_export.csv"'},
    )
