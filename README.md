# Cove · 我们的小海湾

前端 = `index.html`，后端 = `hub.py`。都只用 Python 标准库，不装第三方包。

## 跑起来（Termux）

```bash
# 1）装一次 Python
pkg install python -y

# 2）把这两个文件放进同一个文件夹
mkdir -p ~/Cove
#    （hub.py 和 index.html 放进去）

# 3）跑
cd ~/Cove
python3 hub.py

# 4）浏览器打开
# http://localhost:8000
```

## 这一版有什么

- **便签**（Yoru 写）和 **碎碎念**（Yume 写）—— 点一下就写，**写得进去，刷新还在**
- **在一起的天数** —— 从 2026-07-14 算起
- **日历** —— 有内容的日子会亮；点某一天能翻开看那天的话、心情、待办
- **6 套主题** —— 右上角六个小圆点，点一下就换（这次会记住）

## 数据在哪

全在 `cove.db` 一个文件里。删了 = 从头开始；拷走 = 备份。
（这个文件不会提交到仓库，见 `.gitignore`）

## 还没做

- 聊天（我们）
- 房间（三扇门）
- 主动消息（要等 APK）

## 后端接口

```
GET  /api/today             今天要的一切
GET  /api/posts?who=&limit= 某个人写过的话
POST /api/posts             {who:"yoru"|"yume", text, day}
GET  /api/day/2026-10-02    某一天
POST /api/day/2026-10-02    {yoru_mood, yume_mood, todos}
GET  /api/calendar?y&m      这个月哪几天有内容
GET  /api/settings          读设置
POST /api/settings          {theme, name_yoru, name_yume, ...}
GET  /api/ping              还活着吗
```
