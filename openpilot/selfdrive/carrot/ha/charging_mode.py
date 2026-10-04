"""Interpret fresh passive HVK_01 requests; never infer connector state."""
from datetime import datetime, timezone

FRESHNESS_SECONDS = 90
MODES = {0: 'hv_off', 1: 'hv_on', 3: 'ac_preparing', 4: 'ac_charging', 6: 'dc_charging', 7: 'initializing'}


def charging_mode(data, now=None):
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
