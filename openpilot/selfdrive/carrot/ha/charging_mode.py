"""Interpret fresh passive HVK_01 requests; never infer connector state."""
from datetime import datetime, timezone

FRESHNESS_SECONDS = 90
MODES = {0: 'hv_off', 1: 'hv_on', 3: 'ac_preparing', 4: 'ac_charging', 6: 'dc_charging', 7: 'initializing'}


def request_charging_mode(data, now=None):
    now = now or datetime.now(timezone.utc)
    if isinstance(now, (int, float)):
        now = datetime.fromtimestamp(now, timezone.utc)
    candidates = []
    measured = data.get('field_measured_at') or {}
    for bus in (0, 1):
        key = f'charge_can_bms_request_bus{bus}'
        value = data.get(key)
        if type(value) is not int or not 0 <= value <= 7:
            continue
        try:
            at = datetime.fromisoformat(measured[key].replace('Z', '+00:00'))
            age = (now-at).total_seconds()
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        if 0 <= age <= FRESHNESS_SECONDS:
            candidates.append((at, bus, value))
    result = dict(mode='unknown', charging=None, code=None, bus=None, measured_at=None,
                  driving=data.get('driving') is True or data.get('onroad') is True,
                  source='HVK_01.HVK_BMS_Sollmodus', can_id='0x503', source_kind='request',
                  validation='unavailable', freshness_limit_s=FRESHNESS_SECONDS)
    if not candidates:
        if result['driving']:
            result.update(charging=False, validation='driving')
        return result
    candidates.sort(reverse=True)
    at, bus, code = candidates[0]
    if any(other_code != code and abs((at-other_at).total_seconds()) <= 1
           for other_at, _, other_code in candidates[1:]):
        result['validation'] = 'bus_conflict'
        return result
    mode = MODES.get(code, 'unknown')
    result.update(mode=mode, code=code, bus=bus, measured_at=at.isoformat(),
                  charging=True if code in (4, 6) else False if code in (0, 1, 3) else None,
                  validation='dc_observed_2026_10_04' if code == 6 else 'dbc_definition')
    if data.get('driving') is True or data.get('onroad') is True:
        result.update(charging=False)
        if code in (4, 6):
            result.update(mode='unknown', validation='driving_conflict')
    return result


ACTUAL_MODES = {0: 'hv_off', 1: 'hv_on', 3: 'external_charging', 4: 'ac_charging', 5: 'error', 6: 'dc_charging', 7: 'initializing'}

def charging_mode(data, now=None):
    """Actual BMS mode takes priority, including invalid/stale actual evidence."""
    now = now or datetime.now(timezone.utc)
    if isinstance(now, (int, float)):
        now = datetime.fromtimestamp(now, timezone.utc)
    result = request_charging_mode(data, now)
    keys = [f'bms_actual_mode_bus{bus}' for bus in (0, 1)]
    if not any(key in data for key in keys):
        return result  # Older collector compatibility; power still requires actual CAN.
    candidates = []
    measured = data.get('field_measured_at') or {}
    for bus, key in enumerate(keys):
        code = data.get(key)
        try:
            at = datetime.fromisoformat(measured[key].replace('Z', '+00:00'))
            if type(code) is int and 0 <= code <= 7 and 0 <= (now-at).total_seconds() <= FRESHNESS_SECONDS:
                candidates.append((at, bus, code))
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
    result.update(mode='unknown', charging=False if result['driving'] else None,
                  code=None, bus=None, measured_at=None, source='BMS.actual_mode',
                  can_id='0xCF', source_kind='actual', validation='unavailable')
    if not candidates:
        return result
    candidates.sort(reverse=True)
    at, bus, code = candidates[0]
    if any(c != code and abs((at-t).total_seconds()) <= 1 for t, _, c in candidates[1:]):
        result['validation'] = 'bus_conflict'
        return result
    result.update(mode=ACTUAL_MODES.get(code, 'unknown'), code=code, bus=bus,
                  measured_at=at.isoformat(), charging=True if code in (4, 6) else False if code in (0, 1) else None,
                  validation='ac_dc_observed_2026_10_05' if code in (4, 6) else 'definition')
    if result['driving']:
        result['charging'] = False
        if code in (4, 6):
            result.update(mode='unknown', validation='driving_conflict')
    request = request_charging_mode(data, now)
    result['request_code'] = request['code']
    result['request_disagrees'] = request['code'] is not None and request['code'] != code
    return result

def actual_power_voltage(data, signal):
    """Only same-frame fresh actual evidence. Missing is never coerced to zero."""
    if signal['source_kind'] != 'actual' or signal['bus'] is None:
        return None, None, None
    bus = signal['bus']
    measured = data.get('field_measured_at') or {}
    stamp = signal['measured_at']
    pkey, vkey = f'bms_power_w_bus{bus}', f'bms_voltage_v_bus{bus}'
    power, voltage = data.get(pkey), data.get(vkey)
    if measured.get(pkey) != stamp or measured.get(vkey) != stamp:
        return None, None, None
    if type(voltage) not in (int, float) or not 100 <= voltage <= 800:
        return None, None, stamp
    if type(power) not in (int, float) or not -500000 <= power <= 500000:
        return None, voltage, stamp
    charging = signal['charging']
    return (max(0, power) if charging is True else 0 if charging is False else None), voltage, stamp
