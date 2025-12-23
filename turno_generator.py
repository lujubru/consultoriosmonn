from datetime import datetime, date, timedelta, time
from models import Turno, EstadoTurno, db
from models_admin import (
    HorarioAtencion, 
    ConfiguracionEspecialista, 
    BloqueoHorario,
    EspecialistaEspecialidad
)
from sqlalchemy import and_

class GeneradorTurnos:
    """
    Generador automático de slots de turnos
    """
    
    @staticmethod
    def obtener_slots_disponibles(especialista_id, especialidad_id, fecha):
        """
        Obtiene todos los slots disponibles para un especialista en una fecha
        
        Args:
            especialista_id (int): ID del especialista
            especialidad_id (int): ID de la especialidad
            fecha (date): Fecha para buscar disponibilidad
            
        Returns:
            list: Lista de diccionarios con información de cada slot
        """
        dia_semana = fecha.weekday()
        
        # 1. Verificar que el especialista atiende ese día
        horarios = HorarioAtencion.query.filter(
            HorarioAtencion.especialista_id == especialista_id,
            HorarioAtencion.especialidad_id == especialidad_id,
            HorarioAtencion.dia_semana == dia_semana,
            HorarioAtencion.activo == True
        ).all()
        
        if not horarios:
            return []
        
        # 2. Verificar bloqueos
        bloqueos = BloqueoHorario.query.filter(
            BloqueoHorario.especialista_id == especialista_id,
            BloqueoHorario.fecha_inicio <= fecha,
            BloqueoHorario.fecha_fin >= fecha,
            BloqueoHorario.activo == True
        ).all()
        
        # 3. Obtener configuración del especialista
        config = ConfiguracionEspecialista.query.filter_by(
            especialista_id=especialista_id
        ).first()
        
        if not config:
            return []
        
        # 4. Verificar cupo máximo diario
        turnos_del_dia = Turno.query.filter(
            Turno.especialista_id == especialista_id,
            Turno.fecha == fecha,
            Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
        ).count()
        
        if turnos_del_dia >= config.pacientes_maximos_dia:
            if not config.permite_sobreturnos:
                return []
        
        # 5. Generar todos los slots posibles
        todos_slots = []
        for horario in horarios:
            slots = horario.generar_slots(fecha)
            for hora_inicio, hora_fin in slots:
                # Verificar si el slot está bloqueado
                bloqueado = False
                for bloqueo in bloqueos:
                    if bloqueo.hora_inicio and bloqueo.hora_fin:
                        if (hora_inicio >= bloqueo.hora_inicio and 
                            hora_inicio < bloqueo.hora_fin):
                            bloqueado = True
                            break
                    else:
                        # Bloqueo de día completo
                        bloqueado = True
                        break
                
                if not bloqueado:
                    # Verificar si ya existe un turno en ese horario
                    turno_existente = Turno.query.filter(
                        Turno.especialista_id == especialista_id,
                        Turno.fecha == fecha,
                        Turno.hora == hora_inicio,
                        Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
                    ).first()
                    
                    todos_slots.append({
                        'hora_inicio': hora_inicio,
                        'hora_fin': hora_fin,
                        'disponible': turno_existente is None,
                        'turno_id': turno_existente.id if turno_existente else None
                    })
        
        return todos_slots
    
    @staticmethod
    def obtener_proximas_fechas_disponibles(especialista_id, especialidad_id, dias_adelante=30):
        """
        Obtiene las próximas fechas con al menos un turno disponible
        
        Args:
            especialista_id (int): ID del especialista
            especialidad_id (int): ID de la especialidad
            dias_adelante (int): Cantidad de días a futuro a verificar
            
        Returns:
            list: Lista de fechas con disponibilidad
        """
        fechas_disponibles = []
        fecha_actual = date.today()
        
        for i in range(dias_adelante):
            fecha = fecha_actual + timedelta(days=i)
            slots = GeneradorTurnos.obtener_slots_disponibles(
                especialista_id, 
                especialidad_id, 
                fecha
            )
            
            # Si hay al menos un slot disponible
            if any(slot['disponible'] for slot in slots):
                fechas_disponibles.append({
                    'fecha': fecha,
                    'dia_semana': fecha.weekday(),
                    'slots_disponibles': sum(1 for s in slots if s['disponible']),
                    'slots_totales': len(slots)
                })
        
        return fechas_disponibles
    
    @staticmethod
    def validar_turno(especialista_id, especialidad_id, fecha, hora):
        """
        Valida si se puede crear un turno en el horario especificado
        
        Returns:
            tuple: (es_valido: bool, mensaje: str)
        """
        # 1. Verificar que el especialista atiende ese día y horario
        dia_semana = fecha.weekday()
        
        horario = HorarioAtencion.query.filter(
            HorarioAtencion.especialista_id == especialista_id,
            HorarioAtencion.especialidad_id == especialidad_id,
            HorarioAtencion.dia_semana == dia_semana,
            HorarioAtencion.hora_inicio <= hora,
            HorarioAtencion.hora_fin > hora,
            HorarioAtencion.activo == True
        ).first()
        
        if not horario:
            return False, "El especialista no atiende en ese horario"
        
        # 2. Verificar bloqueos
        bloqueo = BloqueoHorario.query.filter(
            BloqueoHorario.especialista_id == especialista_id,
            BloqueoHorario.fecha_inicio <= fecha,
            BloqueoHorario.fecha_fin >= fecha,
            BloqueoHorario.activo == True
        ).first()
        
        if bloqueo:
            if not bloqueo.hora_inicio:  # Bloqueo de día completo
                return False, f"Horario bloqueado: {bloqueo.motivo}"
            elif bloqueo.hora_inicio <= hora < bloqueo.hora_fin:
                return False, f"Horario bloqueado: {bloqueo.motivo}"
        
        # 3. Verificar turno existente
        turno_existente = Turno.query.filter(
            Turno.especialista_id == especialista_id,
            Turno.fecha == fecha,
            Turno.hora == hora,
            Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
        ).first()
        
        if turno_existente:
            return False, "Ya existe un turno en ese horario"
        
        # 4. Verificar cupo máximo diario
        config = ConfiguracionEspecialista.query.filter_by(
            especialista_id=especialista_id
        ).first()
        
        if config:
            turnos_del_dia = Turno.query.filter(
                Turno.especialista_id == especialista_id,
                Turno.fecha == fecha,
                Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
            ).count()
            
            if turnos_del_dia >= config.pacientes_maximos_dia:
                if not config.permite_sobreturnos:
                    return False, "Cupo máximo diario alcanzado"
                elif turnos_del_dia >= config.pacientes_maximos_dia + config.sobreturnos_maximos:
                    return False, "Cupo máximo de sobreturnos alcanzado"
        
        return True, "Turno válido"