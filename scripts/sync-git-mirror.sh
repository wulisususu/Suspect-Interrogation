#!/usr/bin/env bash
# 在能访问 GitHub 的本机上拉取指定提交，生成浅镜像并推到 RK3588，供板端 runner 离线 checkout。
#
# 背景：板端到 github.com:443 不可达，而 runner 的工作副本是 --filter=blob:none 的
# partial clone，checkout 会逐个回源拉 blob，于是卡在 git checkout 直到 job 超时。
# 本脚本把「某一提交的完整快照」做成 10MB 级浅镜像送到板上，并用 url.insteadOf
# 把 https://github.com/wulisususu/Suspect-Interrogation.git 重定向到本地镜像。
#
# 用法（在本机 Git Bash 下运行）：
#   scripts/sync-git-mirror.sh --pr 28
#   scripts/sync-git-mirror.sh --ref fix/auth-business-review
#   scripts/sync-git-mirror.sh --sha 0f608a558c737508b9eb9233658ab1a52e2829d4
#   scripts/sync-git-mirror.sh --pr 28 --host youyeetoo --proxy http://127.0.0.1:7897
#
# 注意：镜像只含被指定的那一个提交。换 PR / 换分支要重新跑一次。
# 注意：insteadOf 同时作用于 push，板端该用户下 `git push origin` 会指向本地镜像。

set -euo pipefail

HOST="youyeetoo"
PROXY="http://127.0.0.1:7897"
REMOTE_URL="https://github.com/wulisususu/Suspect-Interrogation.git"
MIRROR_PATH="~/git-cache/Suspect-Interrogation.git"
REF=""
PR=""
SHA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr) PR="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --sha) SHA="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --proxy) PROXY="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

REPO_DIR="$(git rev-parse --show-toplevel)"
if [[ -z "$REF" && -z "$PR" && -z "$SHA" ]]; then
  echo "请给出 --pr / --ref / --sha 之一" >&2
  exit 2
fi

echo "== 1/5 拉取 =="
if [[ -n "$PR" ]]; then
  git -C "$REPO_DIR" -c "http.proxy=$PROXY" fetch -q origin "refs/pull/$PR/merge:refs/pull/$PR/merge"
  SHA="$(git -C "$REPO_DIR" rev-parse "refs/pull/$PR/merge")"
  echo "   PR #$PR merge commit: $SHA"
elif [[ -n "$REF" ]]; then
  git -C "$REPO_DIR" -c "http.proxy=$PROXY" fetch -q origin "$REF"
  SHA="$(git -C "$REPO_DIR" rev-parse FETCH_HEAD)"
  echo "   $REF: $SHA"
fi
git -C "$REPO_DIR" cat-file -e "$SHA" 2>/dev/null || { echo "本机没有 $SHA，先 fetch" >&2; exit 3; }

echo "== 2/5 生成浅镜像 =="
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK" >/dev/null 2>&1 || true' EXIT
git init --bare -q "$WORK/ci-mirror.git"
git -C "$WORK/ci-mirror.git" fetch -q --depth 1 "$REPO_DIR" "$SHA:refs/heads/ci-target"
git -C "$WORK/ci-mirror.git" config uploadpack.allowAnySHA1InWant true
git -C "$WORK/ci-mirror.git" config uploadpack.allowReachableSHA1InWant true
SIZE="$(du -sh "$WORK/ci-mirror.git" | cut -f1)"
echo "   镜像大小：$SIZE"

echo "== 3/5 传输 =="
# Git Bash 下 tar -C 绝对路径会被当成远程主机（C:），必须切目录用相对路径。
( cd "$WORK" && tar czf ci-mirror.tgz ci-mirror.git )
scp -q -o ConnectTimeout=10 "$WORK/ci-mirror.tgz" "$HOST:/tmp/ci-mirror.tgz"
echo "   已上传"

echo "== 4/5 板端布置 =="
ssh "$HOST" "set -e
mkdir -p ~/git-cache
rm -rf ~/git-cache/Suspect-Interrogation.git.new
tar xzf /tmp/ci-mirror.tgz -C /tmp
mv /tmp/ci-mirror.git ~/git-cache/Suspect-Interrogation.git.new
git -C ~/git-cache/Suspect-Interrogation.git.new config uploadpack.allowAnySHA1InWant true
git -C ~/git-cache/Suspect-Interrogation.git.new config uploadpack.allowReachableSHA1InWant true
rm -rf ~/git-cache/Suspect-Interrogation.git
mv ~/git-cache/Suspect-Interrogation.git.new ~/git-cache/Suspect-Interrogation.git
git config --global --unset-all 'url./home/youyeetoo/git-cache/Suspect-Interrogation.git.insteadOf' 2>/dev/null || true
git config --global --add 'url./home/youyeetoo/git-cache/Suspect-Interrogation.git.insteadOf' '$REMOTE_URL'
git config --global --add 'url./home/youyeetoo/git-cache/Suspect-Interrogation.git.insteadOf' 'https://github.com/wulisususu/Android-Suspect-Interrogation.git'
rm -f /tmp/ci-mirror.tgz
echo '   镜像就位：' \$(du -sh ~/git-cache/Suspect-Interrogation.git | cut -f1)
git -C ~/git-cache/Suspect-Interrogation.git for-each-ref --format='   %(refname) %(objectname:short)'"

echo "== 5/5 自检 =="
ssh "$HOST" "rm -rf /tmp/fetch-test && git init -q /tmp/fetch-test && cd /tmp/fetch-test \
  && git remote add origin $REMOTE_URL \
  && git fetch -q --depth 1 --no-tags origin $SHA \
  && git cat-file -t $SHA >/dev/null \
  && echo '   本地镜像可取到该提交 ✓' \
  && cd / && rm -rf /tmp/fetch-test"

cat <<EOF

完成。该提交 $SHA 已可在板端离线 checkout。

后续动作：
  - 若有卡在 git checkout 的 job，先取消再重跑：gh run rerun <run-id>
  - 板端旧的工作副本若仍带 partial clone 残留，清一次让 runner 重新 clone：
      ssh $HOST 'rm -rf ~/actions-runner-android/_work/Suspect-Interrogation/Suspect-Interrogation'
  - 生产重部署工作流用的是 codeload 压缩包，不走 git，断网时仍会失败（另行处理）。
EOF
