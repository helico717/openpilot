#pragma once
#include "safety_declarations.h"
#include "safety_defaults.h"

// Experimental signature-Init hypothesis ONLY. No arbitrary signature/payload.
static uint16_t tm01_trial_bus = 0xFFFFU;
static uint32_t tm01_trial_started = 0U;
static uint32_t tm01_trial_last = 0U;
static uint8_t tm01_trial_requests = 0U;
static uint8_t tm01_trial_action = 0U;
static bool tm01_trial_done = false;

static safety_config tm01_trial_init(uint16_t param) {
  tm01_trial_bus = param;
  tm01_trial_started = microsecond_timer_get();
  tm01_trial_last = tm01_trial_started;
  tm01_trial_requests = 0U;
  tm01_trial_action = 0U;
  tm01_trial_done = false;
  controls_allowed = false;
  static const CanMsg msgs[] = {{0x5A7, 0, 8}, {0x5A7, 1, 8}, {0x5A7, 2, 8}};
  return (safety_config){NULL, 0, msgs, 3};
}

static bool tm01_trial_tx_hook(const CANPacket_t *p) {
  uint32_t now = microsecond_timer_get();
  if (tm01_trial_done || (tm01_trial_bus > 2U) || (GET_BUS(p) != tm01_trial_bus) ||
      (GET_ADDR(p) != 0x5A7) || (GET_LEN(p) != 8) || (p->extended != 0U) || (p->fd != 0U) ||
      (get_ts_elapsed(now, tm01_trial_started) >= 5000000U)) {
    return false;
  }
  for (uint8_t i = 0U; i < 8U; i++) {
    if ((i != 6U) && (GET_BYTE(p, i) != 0U)) { return false; }
  }
  uint8_t action = GET_BYTE(p, 6);
  if (action == 0U) {
    tm01_trial_done = true;  // one neutral release, then no more output
    return true;
  }
  if (((action != 2U) && (action != 4U)) || (tm01_trial_requests >= 3U) ||
      ((tm01_trial_action != 0U) && (tm01_trial_action != action)) ||
      ((tm01_trial_requests > 0U) && (get_ts_elapsed(now, tm01_trial_last) < 900000U))) {
    return false;
  }
  tm01_trial_action = action;
  tm01_trial_requests++;
  tm01_trial_last = now;
  return true;
}

const safety_hooks tm01_trial_hooks = {
  .init = tm01_trial_init,
  .rx = default_rx_hook,
  .tx = tm01_trial_tx_hook,
  .fwd = default_fwd_hook,
};
