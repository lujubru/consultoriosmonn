from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import enum

db = SQLAlchemy()

# ENUMS
class RolUsuario(enum.Enum):
    PACIENTE = "paciente"
    ESPECIALISTA = "especialista"
    ADMIN = "admin"
    RECEPCION = "recepcion"

class EstadoTurno(enum.Enum):
    PENDIENTE = "pendiente"
    CONFIRMADO = "confirmado"
    REALIZADO = "realizado"
    CANCELADO = "cancelado"

class EstadoPago(enum.Enum):
    PENDIENTE = "pendiente"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"
    ABONADO_EFECTIVO = "abonado_efectivo"

class TipoMovimiento(enum.Enum):
    INGRESO = "ingreso"
    EGRESO = "egreso"

# MODELOS

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    dni = db.Column(db.String(20), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.Enum(RolUsuario), default=RolUsuario.PACIENTE, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    grupo_familiar = db.relationship('GrupoFamiliar', backref='titular', lazy=True, 
                                     foreign_keys='GrupoFamiliar.usuario_id')
    turnos = db.relationship('Turno', backref='paciente', lazy=True,
                            foreign_keys='Turno.paciente_id')
    turnos_atendidos = db.relationship('Turno', backref='especialista', lazy=True,
                                       foreign_keys='Turno.especialista_id')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<Usuario {self.nombre} {self.apellido} - {self.dni}>'

class GrupoFamiliar(db.Model):
    __tablename__ = 'grupo_familiar'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    dni = db.Column(db.String(20), nullable=False, index=True)
    fecha_nacimiento = db.Column(db.Date)
    parentesco = db.Column(db.String(50))
    activo = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f'<Familiar {self.nombre} {self.apellido} - DNI: {self.dni}>'

class Especialidad(db.Model):
    __tablename__ = 'especialidades'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    direccion = db.Column(db.String(255))  # <--- AGREGAR ESTA LÍNEA
    costo_consulta = db.Column(db.Numeric(10, 2), nullable=False)
    duracion_turno = db.Column(db.Integer, default=30)
    activo = db.Column(db.Boolean, default=True)
    
    turnos = db.relationship('Turno', backref='especialidad', lazy=True)
    
    def __repr__(self):
        return f'<Especialidad {self.nombre}>'

class Turno(db.Model):
    __tablename__ = 'turnos'
    
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    especialista_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidades.id'), nullable=False)
    
    # Puede ser para el titular o un familiar
    familiar_id = db.Column(db.Integer, db.ForeignKey('grupo_familiar.id'))
    familiar = db.relationship('GrupoFamiliar', backref='turnos')
    
    fecha = db.Column(db.Date, nullable=False, index=True)
    hora = db.Column(db.Time, nullable=False, index=True)
    estado = db.Column(db.Enum(EstadoTurno), default=EstadoTurno.PENDIENTE, nullable=False)
    
    motivo_consulta = db.Column(db.Text)
    observaciones = db.Column(db.Text)
    
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_modificacion = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relación con pagos
    pago = db.relationship('Pago', backref='turno', uselist=False, lazy=True)
    
    def __repr__(self):
        return f'<Turno {self.id} - {self.fecha} {self.hora}>'

class Pago(db.Model):
    __tablename__ = 'pagos'
    
    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=False, unique=True)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    estado = db.Column(db.Enum(EstadoPago), default=EstadoPago.PENDIENTE, nullable=False)
    
    # Comprobante comprimido
    comprobante = db.Column(db.LargeBinary)  # Archivo comprimido
    comprobante_nombre = db.Column(db.String(255))
    comprobante_tipo = db.Column(db.String(50))
    
    observaciones = db.Column(db.Text)
    fecha_subida = db.Column(db.DateTime)
    fecha_aprobacion = db.Column(db.DateTime)
    aprobado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Pago {self.id} - Turno {self.turno_id} - {self.estado.value}>'

class Movimiento(db.Model):
    __tablename__ = 'movimientos'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.Enum(TipoMovimiento), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    concepto = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text)
    
    # Si es ingreso, puede estar vinculado a un pago
    pago_id = db.Column(db.Integer, db.ForeignKey('pagos.id'))
    
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    usuario_registro = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    def __repr__(self):
        return f'<Movimiento {self.tipo.value} - ${self.monto}>'

class HorarioDisponible(db.Model):
    __tablename__ = 'horarios_disponibles'
    
    id = db.Column(db.Integer, primary_key=True)
    especialista_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidades.id'), nullable=False)
    dia_semana = db.Column(db.Integer, nullable=False)  # 0=Lunes, 6=Domingo
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f'<Horario Especialista {self.especialista_id} - Día {self.dia_semana}>'