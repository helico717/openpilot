#pragma once
#include <cmath>
#include <fstream>
#include <sstream>
#include <string>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace tm01_trial {
constexpr int MODE = 35;
constexpr const char *LEASE = "/data/carrot_ha/tm01-trial/lease";
struct Lease { bool valid = false; int bus = 0; bool transmit = false; std::string nonce; };
inline Lease parse(const std::string &text, const std::string &boot, double now) {
  Lease l;
  std::string id, extra;
  double started = 0, expires = 0;
  int phase = 0;
  std::istringstream in(text);
  if (!(in >> id >> l.nonce >> started >> expires >> l.bus >> phase) || (in >> extra)) return {};
  if (id != boot || boot.empty() || l.nonce.size() != 32 ||
      l.nonce.find_first_not_of("0123456789abcdef") != std::string::npos ||
      !std::isfinite(now) || !std::isfinite(started) || !std::isfinite(expires) ||
      started > now || expires <= now || expires - started > 12 || expires <= started ||
      l.bus < 0 || l.bus > 2 || (phase != 0 && phase != 1)) return {};
  l.valid = true;
  l.transmit = phase == 1;
  return l;
}
inline Lease read(double now) {
  std::ifstream boot_file("/proc/sys/kernel/random/boot_id");
  std::string boot;
  std::getline(boot_file, boot);
  const int fd = open(LEASE, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
  if (fd < 0) return {};
  struct stat info{};
  char text[257]{};
  const bool regular = fstat(fd, &info) == 0 && S_ISREG(info.st_mode) && info.st_size <= 256;
  const auto n = regular ? ::read(fd, text, sizeof(text)) : -1;
  close(fd);
  if (n < 0 || n > 256) return {};
  return parse(std::string(text, static_cast<size_t>(n)), boot, now);
}
}  // namespace tm01_trial
