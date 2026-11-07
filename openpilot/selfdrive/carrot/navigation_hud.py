"""Display-only navigation signs. Never changes the speed-control candidates."""

ENFORCEMENT_TYPES = (0, 1, 2, 3, 4, 7, 8, 75, 76)


def sign(value):
  return int(value) if 0 < value <= 200 else 0


def cluster_limits(serv, now):
  if serv.carrot_navi_active:
    navi = serv.carrot_navi_control
    if navi.off_route:
      return 0, 0
    speed = navi.speed
    road = sign(speed.road_limit_kph or 0)
    if speed.section_active:
      return road, sign(speed.section_speed_limit_kph)
    if speed.sdi_present and speed.sdi_type in ENFORCEMENT_TYPES and speed.sdi_distance_m > 0:
      if speed.sdi_block_type in (2, 3) and speed.sdi_block_distance_m > 0:
        return road, sign(speed.sdi_block_speed_kph or speed.sdi_speed_limit_kph)
      return road, sign(speed.sdi_speed_limit_kph)
    return road, 0

  # Legacy external data: a heartbeat or a default/fallback 30 is not a road observation.
  legacy_fresh = serv.active_count > 0 or serv.active_kisa_count > 0
  if not legacy_fresh or not 0 <= now - serv.cluster_legacy_road_at < 20:
    return 0, 0
  road = sign(serv.cluster_legacy_road)
  if serv.active_kisa_count > 0:
    enforcement = road if serv.xSpdType in (100, 101) and serv.xSpdDist > -250 else 0
    return road, enforcement
  if serv.nSdiType in ENFORCEMENT_TYPES:
    if serv.nSdiBlockType in (2, 3) and serv.nSdiBlockDist > 0:
      return road, sign(serv.nSdiBlockSpeed or serv.nSdiSpeedLimit)
    if serv.nSdiDist > 0:
      return road, sign(serv.nSdiSpeedLimit)
  return road, 0
