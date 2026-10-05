"""Passive optional telemetry. No CAN writes, Params writes or extra threads."""
import math

OPTIONAL_MESSAGES = ('ZV_02', 'Licht_Anf_01', 'DCDC_03', 'WBA_03', 'Motor_26', 'Motor_Hybrid_06', 'HVK_01')
DOORS = {
    'door_driver_open': 'ZV_FT_offen', 'door_passenger_open': 'ZV_BT_offen',
    'door_rear_driver_open': 'ZV_HFS_offen', 'door_rear_passenger_open': 'ZV_HBFS_offen',
    'trunk_open': 'ZV_HD_offen', 'doors_locked_external': 'ZV_verriegelt_extern_ist',
    'doors_locked_internal': 'ZV_verriegelt_intern_ist',
}
LIGHTS = {
    'light_low_beam_requested': 'BCM1_Abblendlicht_Anf',
    'light_high_beam_requested': 'BCM1_Fernlicht_Anf',
    'light_position_requested': 'BCM1_Standlicht_Anf',
    'light_drl_requested': 'BCM1_Tagfahrlicht_Anf',
    'light_front_fog_requested': 'BCM1_Nebellicht_Anf',
    'light_rear_fog_requested': 'BCM1_Nebelschluss_Fzg_Anf',
    'light_reverse_requested': 'BCM_Rueckfahrlicht_Anf',
}
BMS_MODES = {0: 'hv_inactive', 1: 'driving_hv_active', 2: 'balancing',
             3: 'external_charging', 4: 'ac_charging', 5: 'battery_error', 6: 'dc_charging'}


# Raw diagnostic candidates only. Display text/request modes are NOT a
# validated plug connection signal. Preserve each bus separately for comparison.
CHARGE_CAN_SIGNALS = {
    'plug_text': ('WBA_03', 'WBA_GE_Texte_02', 7),
    'motor_text': ('Motor_26', 'MO_E_Texte', 15),
    'activation_text': ('Motor_Hybrid_06', 'MO_Text_Aktivierung_Antrieb', 15),
    'bms_request': ('HVK_01', 'HVK_BMS_Sollmodus', 7),
    'manager_request': ('HVK_01', 'HVK_HVLM_Sollmodus', 7),
}

def decode_optional(vl_all, bus=None):
    """Only decode samples actually received; zero is a valid closed/off value."""
    def last(message, signal):
        samples = vl_all.get(message, {}).get(signal, [])
        return samples[-1] if samples else None

    result = {}
    if bus in (0, 1):
        for name, (message, signal, maximum) in CHARGE_CAN_SIGNALS.items():
            value = last(message, signal)
            if type(value) in (int, float) and math.isfinite(value) and value == int(value) and 0 <= value <= maximum:
                result[f'charge_can_{name}_bus{bus}'] = int(value)
    for message, fields in (('ZV_02', DOORS), ('Licht_Anf_01', LIGHTS)):
        for key, signal in fields.items():
            value = last(message, signal)
            if value in (0, 1):
                result[key] = bool(value)
    mode = last('BMS_04', 'BMS_IstModus')
    if mode is not None:
        result['bms_mode'] = BMS_MODES.get(mode, 'unknown')
    target = last('BMS_04', 'BMS_Soll_SOC_HiRes')
    if target is not None:
        # DBC values are scaled; raw 2046/2047 are init/error, not percentages.
        result['bms_target_soc_percent'] = target if math.isfinite(target) and 0 <= target <= 100 else None
    temp = last('DCDC_03', 'DC_Temperatur')
    if temp is not None:
        # raw 254/255 -> 214/215 C are init/error. This is NOT pack temperature.
        result['dcdc_temperature_c'] = temp if math.isfinite(temp) and -40 <= temp <= 213 else None
    return result


def device_health(device):
    result = {}
    for source, key, maximum in (
        ('cpuTempC', 'comma_cpu_temperature_c', True),
        ('gpuTempC', 'comma_gpu_temperature_c', True),
        ('cpuUsagePercent', 'comma_cpu_usage_percent', False),
    ):
        samples = [float(v) for v in getattr(device, source, []) if math.isfinite(v)]
        if samples:
            result[key] = round(max(samples) if maximum else sum(samples) / len(samples), 1)
    for source, key in (
        ('freeSpacePercent', 'comma_storage_free_percent'),
        ('memoryUsagePercent', 'comma_memory_usage_percent'),
        ('fanSpeedPercentDesired', 'comma_fan_requested_percent'),
    ):
        value = getattr(device, source, None)
        if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 100:
            result[key] = round(value, 1)
    for source, key in (('thermalStatus', 'comma_thermal_status'),
                        ('networkType', 'comma_network_type'),
                        ('networkStrength', 'comma_network_strength')):
        value = getattr(device, source, None)
        if value is not None:
            result[key] = str(value)
    return result


def decode_battery_energy(vl_all):
    """Reject MEB DBC Init/Fehler codes; try the alternate valid signal."""
    for message, signal, maximum in [('Motor_16','MO_Energieinhalt_BMS',102325),
                                     ('HVEM_02','HVEM_Nutzbare_Energie',102200)]:
        samples=vl_all.get(message, {}).get(signal)
        if samples:
            value=samples[-1] if isinstance(samples,(list,tuple)) else samples
            if type(value) in (int,float) and math.isfinite(value) and 0 < value <= maximum:
                return float(value)
    return None


BATTERY_MONITOR_KEYS = {
    'battery_min_temperature_c', 'battery_max_temperature_c',
    'battery_cell_min_voltage_v', 'battery_cell_max_voltage_v',
    'battery_cell_voltage_delta_mv', 'battery_charge_temperature_status',
}
CHARGE_TEMPERATURE_STATES = {1: 'below_optimal', 2: 'optimal', 3: 'above_optimal'}

def decode_battery_monitoring(address, payload):
    """Passive MEB observations; do not affect SOC or charging decisions.

    Definitions/vehicle evidence: carrot-ha/docs/raw-can-full-audit-2026-10-05.md.
    Initialisation codes must clear an existing value, not refresh it.
    Cell extrema and their difference always come from the same frame.
    """
    if address not in (0x16A954A6, 0x1A5555B2) or len(payload) != 8:
        return {}
    b = payload
    if address == 0x1A5555B2:
        code = (int.from_bytes(b, 'little') >> 15) & 7
        return {'battery_charge_temperature_status': CHARGE_TEMPERATURE_STATES.get(code)}
    low = b[4] * .5 - 40 if b[4] < 254 else None
    high = b[3] * .5 - 40 if b[3] < 254 else None
    if low is not None and high is not None and low > high:
        low = high = None
    max_raw = ((b[6] & 15) << 8) | b[5]
    min_raw = (b[7] << 4) | (b[6] >> 4)
    # Startup has invalid extrema together with the temperature sentinels.
    minimum = min_raw + 1000 if min_raw < 4094 and b[3] < 254 and b[4] < 254 else None
    maximum = max_raw + 1000 if max_raw < 4094 and b[3] < 254 and b[4] < 254 else None
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum = maximum = None
    return {
        'battery_min_temperature_c': low, 'battery_max_temperature_c': high,
        'battery_cell_min_voltage_v': minimum / 1000 if minimum is not None else None,
        'battery_cell_max_voltage_v': maximum / 1000 if maximum is not None else None,
        'battery_cell_voltage_delta_mv': maximum - minimum if maximum is not None and minimum is not None else None,
    }


BMS_ACTUAL_KEYS = {f'bms_{field}_bus{bus}' for field in ('actual_mode', 'power_w', 'voltage_v') for bus in (0, 1)}
BATTERY_MONITOR_KEYS.update(BMS_ACTUAL_KEYS)

def decode_bms_actual(payload, bus):
    """Receive-only 0xCF, AC/DC field-tested 2026-10-05. Positive is charging."""
    if len(payload) != 8 or bus not in (0, 1):
        return {}
    b = payload
    mode = b[2] & 7
    current = ((((b[4] & 127) << 8) | b[3]) - 16300) * .1
    voltage = ((b[7] << 4) | (b[6] >> 4)) * .25
    valid = mode != 7 and 100 <= voltage <= 800 and abs(current) <= 1000
    return {f'bms_actual_mode_bus{bus}': mode,
            f'bms_power_w_bus{bus}': round(current * voltage, 2) if valid else None,
            f'bms_voltage_v_bus{bus}': voltage if valid else None}
