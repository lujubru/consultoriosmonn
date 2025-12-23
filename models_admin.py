from models import db
from datetime import datetime, time, timedelta
import enum

# ==================== ENUMS ADICIONALES ====================

class DiaSemana(enum.Enum):
    LUNES = 0
    MARTES = 1
    MIERCOLES = 2
    JUEVES = 3
    VIERNES = 4
    SABADO = 5
    DOMINGO = 6

class EstadoEspecialidad(enum.Enum):
    ACTIVA = "activa"
    INACTIVA = "inactiva"

# ==================== MODELOS ====================

class ConfiguracionEspecialista(db.Model):
    """
    Configuración general del especialista
    Define cupos diarios, duración de turnos, etc.
    """
    __tablename__ = 'configuracion_especialista'
    
    id = db.Column(db.Integer, primary_key=True)
    especialista_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    
    # Configuración de turnos
    duracion_turno_minutos = db.Column(db.Integer, default=30, nullable=False)  # Ej: 15, 30, 45 min
    pacientes_maximos_dia = db.Column(db.Integer, default=20, nullable=False)
    
    # Tiempo de buffer entre turnos (opcional)
    tiempo_buffer_minutos = db.Column(db.Integer, default=0)  # Ej: 5 min de descanso
    
    # Permitir sobreturnos excepcionales
    permite_sobreturnos = db.Column(db.Boolean, default=False)
    sobreturnos_maximos = db.Column(db.Integer, default=0)
    
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    especialista = db.relationship('Usuario', backref='configuracion_especialista')
    
    def __repr__(self):
        return f'<ConfigEspecialista {self.especialista_id}>'


class EspecialistaEspecialidad(db.Model):
    """
    Tabla de relación muchos a muchos
    Un especialista puede tener múltiples especialidades
    Una especialidad puede tener múltiples especialistas
    """
    __tablename__ = 'especialista_especialidad'
    
    id = db.Column(db.Integer, primary_key=True)
    especialista_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidades.id'), nullable=False)
    
    # Costo específico de este especialista para esta especialidad
    # (puede ser diferente al costo base de la especialidad)
    costo_consulta = db.Column(db.Numeric(10, 2))
    
    activo = db.Column(db.Boolean, default=True)
    fecha_asignacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    especialista = db.relationship('Usuario', backref='especialidades_asignadas')
    especialidad = db.relationship('Especialidad', backref='especialistas_asignados')
    
    # Índice único compuesto
    __table_args__ = (
        db.UniqueConstraint('especialista_id', 'especialidad_id', name='uq_especialista_especialidad'),
    )
    
    def __repr__(self):
        return f'<EspecialistaEspecialidad E{self.especialista_id}-Esp{self.especialidad_id}>'


class HorarioAtencion(db.Model):
    """
    Horarios de atención del especialista
    Puede tener múltiples horarios por día (ej: mañana y tarde)
    """
    __tablename__ = 'horarios_atencion'
    
    id = db.Column(db.Integer, primary_key=True)
    especialista_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidades.id'), nullable=False)
    
    # Día de la semana (0=Lunes, 6=Domingo)
    dia_semana = db.Column(db.Integer, nullable=False)
    
    # Rango horario
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    
    # Sobrescribir duración de turno para este horario específico (opcional)
    duracion_turno_custom = db.Column(db.Integer)  # Si es NULL, usa la configuración general
    
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    especialista = db.relationship('Usuario', backref='horarios_atencion')
    especialidad = db.relationship('Especialidad', backref='horarios_disponibles')
    
    # Índices
    __table_args__ = (
        db.Index('idx_horario_especialista_dia', 'especialista_id', 'dia_semana'),
    )
    
    def __repr__(self):
        dias = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        return f'<Horario {dias[self.dia_semana]} {self.hora_inicio}-{self.hora_fin}>'
    
    def generar_slots(self, fecha):
        """
        Genera los slots de turnos disponibles para una fecha específica
        
        Args:
            fecha (date): Fecha para la cual generar slots
            
        Returns:
            list: Lista de tuplas (hora_inicio, hora_fin) para cada slot
        """
        slots = []
        
        # Obtener duración del turno
        if self.duracion_turno_custom:
            duracion = self.duracion_turno_custom
        else:
            config = ConfiguracionEspecialista.query.filter_by(
                especialista_id=self.especialista_id
            ).first()
            duracion = config.duracion_turno_minutos if config else 30
        
        # Generar slots
        hora_actual = datetime.combine(fecha, self.hora_inicio)
        hora_limite = datetime.combine(fecha, self.hora_fin)
        
        while hora_actual < hora_limite:
            hora_fin_slot = hora_actual + timedelta(minutes=duracion)
            
            if hora_fin_slot <= hora_limite:
                slots.append((
                    hora_actual.time(),
                    hora_fin_slot.time()
                ))
            
            # Agregar buffer si existe
            config = ConfiguracionEspecialista.query.filter_by(
                especialista_id=self.especialista_id
            ).first()
            
            buffer = config.tiempo_buffer_minutos if config else 0
            hora_actual = hora_fin_slot + timedelta(minutes=buffer)
        
        return slots


class BloqueoHorario(db.Model):
    """
    Bloqueos de horarios (vacaciones, ausencias, etc.)
    """
    __tablename__ = 'bloqueos_horario'
    
    id = db.Column(db.Integer, primary_key=True)
    especialista_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    # Rango de fechas bloqueadas
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    
    # Bloqueo de horario específico o día completo
    hora_inicio = db.Column(db.Time)  # NULL = todo el día
    hora_fin = db.Column(db.Time)
    
    motivo = db.Column(db.String(255))
    observaciones = db.Column(db.Text)
    
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    # Relaciones
    especialista = db.relationship('Usuario', foreign_keys=[especialista_id], backref='bloqueos')
    
    def __repr__(self):
        return f'<Bloqueo {self.fecha_inicio} a {self.fecha_fin}>'


class AuditoriaAdmin(db.Model):
    """
    Log de acciones administrativas
    """
    __tablename__ = 'auditoria_admin'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    accion = db.Column(db.String(100), nullable=False)  # Ej: "CREAR_ESPECIALISTA", "MODIFICAR_HORARIO"
    tabla_afectada = db.Column(db.String(100))
    registro_id = db.Column(db.Integer)
    
    datos_anteriores = db.Column(db.JSON)  # Estado antes del cambio
    datos_nuevos = db.Column(db.JSON)  # Estado después del cambio
    
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(255))
    
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relaciones
    usuario = db.relationship('Usuario', backref='acciones_admin')
    
    def __repr__(self):
        return f'<Auditoria {self.accion} por {self.usuario_id}>'