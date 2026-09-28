"""Passive optional telemetry. No CAN writes, Params writes or extra threads."""
import math

OPTIONAL_MESSAGES = ('ZV_02', 'Licht_Anf_01', 'DCDC_03')
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


def decode_optional(vl_all):
    """Only decode samples actually received; zero is a valid closed/off value."""
    def last(message, signal):
        samples = vl_all.get(message, {}).get(signal, [])
        return samples[-1] if samples else None

    result = {}
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
