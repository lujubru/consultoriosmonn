from models import db
from datetime import datetime, date
import enum

# ==================== ENUMS ====================

class TipoPlan(enum.Enum):
    INDIVIDUAL = "individual"
    PAREJA = "pareja"
    FAMILIAR = "familiar"
    FAMILIAR_MAXI = "familiar_maxi"

class EstadoSuscripcion(enum.Enum):
    PENDIENTE = "pendiente"  # Solicitud enviada, esperando aprobación
    ACTIVA = "activa"  # Suscripción aprobada y activa
    SUSPENDIDA = "suspendida"  # Suspendida por falta de pago
    CANCELADA = "cancelada"  # Cancelada por el usuario o admin
    VENCIDA = "vencida"  # Periodo vencido

class EstadoPagoMensual(enum.Enum):
    PENDIENTE = "pendiente"  # Comprobante subido, esperando revisión
    APROBADO = "aprobado"  # Pago aprobado
    RECHAZADO = "rechazado"  # Pago rechazado
    VENCIDO = "vencido"  # No se subió comprobante a tiempo

# ==================== MODELOS ====================

class PlanPrepaga(db.Model):
    """
    Definición de los planes de prepaga disponibles
    """
    __tablename__ = 'planes_prepaga'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.Enum(TipoPlan), nullable=False, unique=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    
    # Costos y límites
    precio_mensual = db.Column(db.Numeric(10, 2), nullable=False)
    consultas_incluidas = db.Column(db.Integer, default=10)  # Por persona
    personas_maximas = db.Column(db.Integer, default=1)  # 1=Individual, 2=Pareja, 4=Familiar, etc
    
    # Características especiales
    incluye_medico_online = db.Column(db.Boolean, default=False)
    
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    suscripciones = db.relationship('SuscripcionPrepaga', back_populates='plan', lazy='dynamic')
    
    def __repr__(self):
        return f'<PlanPrepaga {self.nombre}>'


class SuscripcionPrepaga(db.Model):
    """
    Suscripción de un usuario a un plan de prepaga
    """
    __tablename__ = 'suscripciones_prepaga'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('planes_prepaga.id'), nullable=False)
    
    # Estado y fechas
    estado = db.Column(db.Enum(EstadoSuscripcion), default=EstadoSuscripcion.PENDIENTE, nullable=False)
    fecha_solicitud = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_aprobacion = db.Column(db.DateTime)
    fecha_inicio = db.Column(db.Date)  # Fecha de inicio del plan
    fecha_fin = db.Column(db.Date)  # Fecha de vencimiento (si aplica)
    
    # Control de consultas
    consultas_consumidas = db.Column(db.Integer, default=0)
    consultas_disponibles = db.Column(db.Integer)  # Se calcula al aprobar
    
    # Comprobante de solicitud inicial
    comprobante_inicial = db.Column(db.LargeBinary)
    comprobante_inicial_nombre = db.Column(db.String(255))
    comprobante_inicial_tipo = db.Column(db.String(100))
    fecha_subida_inicial = db.Column(db.DateTime)
    
    # Observaciones
    observaciones = db.Column(db.Text)
    motivo_rechazo = db.Column(db.Text)
    
    # Auditoría
    aprobado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    cancelado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    fecha_cancelacion = db.Column(db.DateTime)
    
    # Relaciones
    usuario = db.relationship('Usuario', foreign_keys=[usuario_id], backref='suscripcion_prepaga')
    plan = db.relationship('PlanPrepaga', back_populates='suscripciones')
    pagos_mensuales = db.relationship('PagoMensualPrepaga', back_populates='suscripcion', lazy='dynamic')
    
    # Índices
    __table_args__ = (
        db.Index('idx_suscripcion_usuario_estado', 'usuario_id', 'estado'),
    )
    
    def __repr__(self):
        return f'<SuscripcionPrepaga U{self.usuario_id}-P{self.plan_id}>'
    
    def tiene_consultas_disponibles(self):
        """Verifica si aún tiene consultas disponibles"""
        if self.estado != EstadoSuscripcion.ACTIVA:
            return False
        return self.consultas_consumidas < self.consultas_disponibles
    
    def consumir_consulta(self):
        """Consume una consulta del plan"""
        if self.tiene_consultas_disponibles():
            self.consultas_consumidas += 1
            return True
        return False
    
    def consultas_restantes(self):
        """Retorna el número de consultas restantes"""
        return max(0, self.consultas_disponibles - self.consultas_consumidas)


class PagoMensualPrepaga(db.Model):
    """
    Pagos mensuales de una suscripción de prepaga
    """
    __tablename__ = 'pagos_mensuales_prepaga'
    
    id = db.Column(db.Integer, primary_key=True)
    suscripcion_id = db.Column(db.Integer, db.ForeignKey('suscripciones_prepaga.id'), nullable=False)
    
    # Periodo de pago
    mes = db.Column(db.Integer, nullable=False)  # 1-12
    anio = db.Column(db.Integer, nullable=False)
    
    # Monto
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Estado
    estado = db.Column(db.Enum(EstadoPagoMensual), default=EstadoPagoMensual.PENDIENTE, nullable=False)
    
    # Comprobante
    comprobante = db.Column(db.LargeBinary)
    comprobante_nombre = db.Column(db.String(255))
    comprobante_tipo = db.Column(db.String(100))
    fecha_subida = db.Column(db.DateTime)
    
    # Fechas importantes
    fecha_vencimiento = db.Column(db.Date, nullable=False)  # Fecha límite para pagar
    fecha_aprobacion = db.Column(db.DateTime)
    
    # Auditoría
    aprobado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    observaciones = db.Column(db.Text)
    motivo_rechazo = db.Column(db.Text)
    
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    suscripcion = db.relationship('SuscripcionPrepaga', back_populates='pagos_mensuales')
    aprobador = db.relationship('Usuario', foreign_keys=[aprobado_por])
    
    # Índices
    __table_args__ = (
        db.UniqueConstraint('suscripcion_id', 'mes', 'anio', name='uq_pago_mensual'),
        db.Index('idx_pago_mensual_estado', 'estado'),
    )
    
    def __repr__(self):
        return f'<PagoMensualPrepaga S{self.suscripcion_id}-{self.mes}/{self.anio}>'
    
    @property
    def periodo_texto(self):
        """Retorna el periodo en formato legible"""
        meses = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
            5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }
        return f"{meses.get(self.mes, '')} {self.anio}"


class HistorialConsultasPrepaga(db.Model):
    """
    Historial de consumo de consultas de la prepaga
    """
    __tablename__ = 'historial_consultas_prepaga'
    
    id = db.Column(db.Integer, primary_key=True)
    suscripcion_id = db.Column(db.Integer, db.ForeignKey('suscripciones_prepaga.id'), nullable=False)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos.id'), nullable=False)
    
    fecha_consumo = db.Column(db.DateTime, default=datetime.utcnow)
    consultas_antes = db.Column(db.Integer)  # Consultas disponibles antes
    consultas_despues = db.Column(db.Integer)  # Consultas disponibles después
    
    # Relaciones
    suscripcion = db.relationship('SuscripcionPrepaga', backref='historial_consumo')
    turno = db.relationship('Turno', backref='consumo_prepaga')
    
    def __repr__(self):
        return f'<HistorialConsulta S{self.suscripcion_id}-T{self.turno_id}>'