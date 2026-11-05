#!/usr/bin/env bash
# تجهيز سيرفر «أكا ميديا» (Ubuntu 22/24) كمشغّل GitHub Actions ذاتي: الأسرار تبقى بـ GitHub ولا تُكتب على السيرفر يدوياً.
# الاستخدام (يلصقه إيهاب بنفسه، والرمز من صفحة GitHub: Settings ← Actions ← Runners ← New self-hosted runner):
#   curl -fsSL https://raw.githubusercontent.com/ehabkadim2026-byte/hobi-ajel/main/tools/server/setup.sh | sudo bash -s -- <TOKEN>
set -euo pipefail
TOKEN="${1:?ضع رمز التسجيل من صفحة GitHub بعد الأمر}"
URL="https://github.com/ehabkadim2026-byte/hobi-ajel"
export DEBIAN_FRONTEND=noninteractive
echo "== 1/5 تحديث وتثبيت الأدوات"
apt-get update -y -q
apt-get install -y -q curl git jq tar python3 python3-venv python3-pip ffmpeg libraqm0 fonts-noto-core ca-certificates >/dev/null
echo "== 2/5 ذاكرة احتياطية (swap 2GB) لأن الرام 2GB"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo "== 3/5 مستخدم التشغيل"
id runner >/dev/null 2>&1 || useradd -m -s /bin/bash runner
ARCH=$(uname -m); case "$ARCH" in x86_64) A=x64;; aarch64|arm64) A=arm64;; *) echo "معمارية غير مدعومة $ARCH"; exit 1;; esac
VER=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/^v//')
echo "== 4/5 تنزيل المشغّل v$VER ($A)"
cd /home/runner
curl -fsSL -o runner.tgz "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-linux-${A}-${VER}.tar.gz"
for n in 1 2; do  # مشغّلان: واحد للجولة الرئيسية وواحد للمهام القصيرة حتى لا ينتظر أحدهما الآخر
  d=/home/runner/r$n; mkdir -p $d; tar xzf runner.tgz -C $d
  [ "$n" = 1 ] && $d/bin/installdependencies.sh >/dev/null 2>&1 || true
  chown -R runner:runner $d
  if [ ! -f $d/.runner ]; then
    sudo -u runner $d/config.sh --unattended --url "$URL" --token "$TOKEN" --name "aka-$n" --labels "aka" --replace
  fi
  (cd $d && ./svc.sh install runner >/dev/null && ./svc.sh start >/dev/null)
done
rm -f runner.tgz
echo "== 5/5 فحص"
systemctl --no-pager --type=service | grep -c actions.runner || true
echo "✅ تم: المشغّلان aka-1 و aka-2 يعملان. أبلغ Claude بكلمة «تم»."
