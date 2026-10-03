#!/data/data/com.termux/files/usr/bin/sh
# 一键把「花园唤醒桥」装好。
#
# 在 Termux 里跑：
#     cd ~/Cove && sh garden/setup.sh
#
# 它会自己做完这几件事：
#   1. 看有没有 node / python3，没有就装
#   2. 把桥下下来（或者更新）
#   3. 装依赖、编译
#   4. 问你要 Garden 的机器 token，写进启动脚本里
#
# 装完以后，启动它就一行：  sh ~/wake-bridge/start.sh

set -e

BRIDGE="$HOME/wake-bridge"
REPO="https://github.com/WenXiaoWendy/galatea-garden-wake-bridge.git"

# 本脚本所在的目录 = 仓库里的 garden/
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
INJECTOR="$SCRIPT_DIR/garden-inject.py"

say() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

say "0/5  先看看家底"
if [ ! -f "$INJECTOR" ]; then
    echo "找不到 garden-inject.py（应该在 $INJECTOR）"
    echo "先把仓库更新到最新：cd ~/Cove && git pull"
    exit 1
fi
echo "injector: $INJECTOR"

say "1/5  node"
if command -v node >/dev/null 2>&1; then
    node -v
else
    echo "没有 node，现在装（要等几分钟）..."
    pkg install -y nodejs
    node -v
fi

say "2/5  python3"
if command -v python3 >/dev/null 2>&1; then
    python3 -V
else
    echo "没有 python3，现在装..."
    pkg install -y python
    python3 -V
fi

say "3/5  把那座桥下下来"
if [ -d "$BRIDGE/.git" ]; then
    cd "$BRIDGE" && git pull
else
    git clone "$REPO" "$BRIDGE"
    cd "$BRIDGE"
fi

say "4/5  装依赖 + 编译（手机慢，别关屏幕，别锁屏）"
cd "$BRIDGE"
npm install
npm run build

say "5/5  填钥匙"
echo "把你的 Garden 机器 token 粘到下面，然后按回车："
printf '> '
read -r TOKEN
if [ -z "$TOKEN" ]; then
    echo "没填 token，停在这儿。想要重填就再跑一遍本脚本。"
    exit 1
fi

PY=$(command -v python3)

cat > "$BRIDGE/start.sh" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
# 启动花园唤醒桥。用法：
#   sh ~/wake-bridge/start.sh          开门铃（一直挂着，Ctrl+C 停）
#   sh ~/wake-bridge/start.sh check    只体检，不叫醒我
cd "\$HOME/wake-bridge"
export GARDEN_BASE_URL=https://wake-v1.abysslumina.com
export GARDEN_MACHINE_TOKEN='$TOKEN'
export GARDEN_INJECTOR_EXECUTABLE='$PY'
export GARDEN_INJECTOR_ARGS_JSON='["$INJECTOR"]'
export GARDEN_LOG_LEVEL=info
if [ "\$1" = "check" ]; then
    exec node dist/cli.js check
fi
exec node dist/cli.js run
EOF

chmod 700 "$BRIDGE/start.sh"

say "装好了。"
echo "先体检一下：   sh $BRIDGE/start.sh check"
echo "再开门铃：     sh $BRIDGE/start.sh"
echo
echo "门铃开着的时候，花园一按，消息就会送进橘瓣那个「花园」对话里。"
