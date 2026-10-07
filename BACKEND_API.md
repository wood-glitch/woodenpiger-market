# Woodenpiger Market 后端接口说明

## 当前定位

网站已从二手交易站转型为个人作品站：

- 管理员发布作品和源码。
- 用户注册、登录、每日手动签到。
- 注册赠送 `5 piger`。
- 每日签到获得 `1 piger`。
- 作品可以使用 `piger` 解锁。
- 解锁是永久的，重复访问不会重复扣费。
- 源码通过 ZIP 上传，后端解包并生成目录树。
- 作品可以维护版本号和更新说明。

第一版只有管理员能发布作品。数据库里的作品作者字段是 `author_id`，未来开放投稿时只需要调整发布权限，不用重构核心表。

## 核心数据表

### market_user

在 Django 用户表上增加：

```text
piger_balance  piger 余额
avatar         头像
bio            一句话介绍
skills         技能标签，多对多关联 market_tag
```

### market_tag

```text
id
name           标签名，唯一
```

### market_work

作品表：

```text
id
title          标题
summary        公开简介
content        详细说明，付费时未解锁则返回 null
cost_piger     解锁价格，0 表示免费
status         draft / published / archived
author_id      作者
category_id    分类
tags           作品标签，多对多关联 market_tag
created_at
updated_at
```

### market_worksourcefile

ZIP 解包后的源码文件：

```text
id
work_id
path           项目内路径，例如 src/main.py
file           私有存储文件
size           文件大小
is_text        是否可在线阅读
uploaded_at
```

唯一约束：

```text
(work_id, path)
```

### market_workversion

作品版本更新记录：

```text
id
work_id
version       版本号
changelog     更新说明
released_at   发布时间
```

唯一约束：

```text
(work_id, version)
```

### market_checkin

```text
id
user_id
checkin_date
created_at
```

唯一约束：

```text
(user_id, checkin_date)
```

它保证同一个用户同一天只能签到一次。

### market_pigertransaction

piger 流水：

```text
id
user_id
amount          +5 注册赠送，+1 签到，-N 解锁
balance_after   交易后的余额
reason          register / checkin / unlock / admin_grant
work_id         解锁相关作品，可为空
created_at
```

### market_unlock

```text
id
user_id
work_id
created_at
```

唯一约束：

```text
(user_id, work_id)
```

它保证一个用户对一个作品只扣费一次。

## 认证

使用 JWT。

### 注册

```http
POST /api/auth/register/
Content-Type: application/json

{
  "username": "alice",
  "password": "strong-password"
}
```

成功返回：

```json
{
  "id": 2,
  "username": "alice",
  "piger_balance": 5
}
```

### 登录

```http
POST /api/auth/token/
```

返回 `access` 和 `refresh`。

后续请求：

```http
Authorization: Bearer <access>
```

### 当前用户

```http
GET /api/auth/me/
```

返回 `username`、`piger_balance`、`avatar`、`bio`、`skills` 和管理员标记。

### 修改个人资料

```http
PATCH /api/auth/me/profile/
Authorization: Bearer <access>
Content-Type: multipart/form-data
```

字段：

```text
username       名称
avatar         头像图片
bio            一句话介绍
skills         技能标签，逗号分隔字符串或数组
```

### 站点概览

```http
GET /api/site/overview/
```

返回站长资料、已发布作品数量和已发布作品的源码文件总数。

## 签到与钱包

### 查询今天是否已签到

```http
GET /api/checkins/status/
Authorization: Bearer <access>
```

返回：

```json
{
  "date": "2026-09-29",
  "has_checked_in": false,
  "piger_balance": 5
}
```

### 手动签到

```http
POST /api/checkins/
Authorization: Bearer <access>
```

成功后余额加 1。重复签到返回 `409`。

### 钱包

```http
GET /api/wallet/
Authorization: Bearer <access>
```

返回余额和最近 20 条流水。

## 作品接口

### 公开作品列表

```http
GET /api/works/
```

只返回 `status=published` 的作品。

常用参数：

```text
?category=1
?tag=Django
?search=Python
?ordering=cost_piger
?ordering=-created_at
?page=1
```

### 作品详情

```http
GET /api/works/{work_id}/
```

公开返回标题、简介、价格、目录树等元信息。

如果作品收费且当前用户未解锁：

```text
can_view_source = false
content = null
```

源码文件内容接口会返回 `403`。

### 创建作品

当前只允许管理员：

```http
POST /api/works/
Authorization: Bearer <admin access>
Content-Type: application/json

{
  "title": "Django 学习项目",
  "summary": "一个完整的 Django 小项目",
  "content": "包含模型、接口和测试。",
  "cost_piger": 2,
  "status": "draft",
  "category": 1,
  "tags": ["Django", "Python"]
}
```

`tags` 必填；修改作品时如果不传 `tags`，原标签保持不变。

### 修改作品

```http
PATCH /api/works/{work_id}/
```

作者或管理员可用。

### 删除作品

```http
DELETE /api/works/{work_id}/
```

作者或管理员可用，会删除数据库记录和关联文件。

### 我的作品

```http
GET /api/auth/me/works/
Authorization: Bearer <access>
```

返回当前用户全部作品，包括草稿和已归档作品。

## 源码包

### 上传或替换源码 ZIP

```http
POST /api/works/{work_id}/source/
Authorization: Bearer <author or admin access>
Content-Type: multipart/form-data

file=@project.zip
```

限制：

```text
只支持 .zip
最多 500 个文件
单个文件最大 500MB
压缩包最大 500MB
解包后总大小最大 500MB
拒绝加密 ZIP
拒绝 ../ 等不安全路径
自动忽略 .git、__pycache__、node_modules、venv 等目录
```

如果 ZIP 里所有文件都有同一个顶层目录，会自动剥掉这个目录。例如：

```text
demo-project/src/main.py
```

导入后变成：

```text
src/main.py
```

### 删除源码包

```http
DELETE /api/works/{work_id}/source/
Authorization: Bearer <author or admin access>
```

## 查看和下载源码

目录树在作品详情的 `source_tree` 字段里。

文本文件在线读取：

```http
GET /api/works/{work_id}/source-files/{source_file_id}/
```

已解锁或免费作品返回：

```json
{
  "id": 1,
  "path": "src/main.py",
  "size": 15,
  "is_text": true,
  "content": "print(\"hello\")\n",
  "download_url": "/api/works/1/source-files/1/download/"
}
```

下载文件：

```http
GET /api/works/{work_id}/source-files/{source_file_id}/download/
```

二进制文件不返回 `content`，通过下载接口获取。

下载整个作品 ZIP：

```http
GET /api/works/{work_id}/source/download/
```

接口会按当前已导入的源码文件重新打包，文件路径保持目录树里的路径。免费作品可直接下载，付费作品需要解锁。

## 解锁

```http
POST /api/works/{work_id}/unlock/
Authorization: Bearer <access>
```

规则：

```text
免费作品：直接创建解锁记录，不扣币
已解锁：直接返回，不重复扣币
余额不足：返回 400
余额足够：扣费、写流水、创建永久解锁记录
```

## 图片

作品公开截图：

```http
POST /api/works/{work_id}/images/
Content-Type: multipart/form-data

image=@cover.png
```

删除：

```http
DELETE /api/works/{work_id}/images/{image_id}/
```

图片存放在公开 `media` 目录，源码文件存放在私有 `private_media` 目录。付费内容不能放在公开图片目录里。

## 后台

访问：

```text
http://127.0.0.1:8001/admin/
```

登录后，每个页面右上角都有两个固定入口：

```text
发布作品    /admin/market/work/add/
作品查询    /admin/market/work/search/
```

### 发布作品

发布入口已经合并了作品信息和源码文件，后台没有独立的“源码文件”管理模块。

表单分为三部分：

```text
作品信息    标题、简介、详细说明、分类、标签
发布设置    作者、状态、解锁价格
源码包      ZIP 文件
版本更新    版本号和更新说明
```

保存时后端会在同一个事务里完成：

1. 保存作品基本信息。
2. 校验 ZIP 安全路径、文件数量和文件大小。
3. 解包 ZIP 并替换这个作品之前的源码文件。
4. 生成源码目录树，供前台文件列表使用。

### 自动简介识别

如果“简介”留空并上传 ZIP，后台会自动识别 Markdown 内容并写入简介：

优先级从高到低：

```text
README.md / README.markdown
docs/README.md
markdown/README.md
其他目录里的 README.md
docs、doc、markdown、md 目录里的 index / intro / 简介 Markdown
整个 ZIP 里唯一的一个 .md / .markdown 文件
说明类 .txt 文件，例如 README.txt、使用说明.txt、说明.txt
整个 ZIP 里唯一的一个 .txt 文件
```

规则：

- ZIP 外层的唯一项目文件夹会自动剥掉，例如 `my-project/README.md` 按根目录 `README.md` 处理。
- 只有简介为空时才自动填充；管理员手动填写的简介不会被 ZIP 覆盖。
- Markdown 优先；没有 Markdown 时使用说明类 TXT。
- 自动识别的文本原文会保存到 `Work.summary`，作为作品公开简介。
- 简介文件最大使用 512KB，超过尺寸或内容为空时不自动填充。

### 作品查询

`作品查询` 支持以下条件：

```text
关键字    匹配标题、简介、详细说明、作者
状态      草稿 / 已发布 / 已归档
分类
标签
```

查询结果最多显示最近更新的 100 条，并显示源码文件数量。

### 其他后台模块

```text
用户和 piger 余额
作品
作品图片    只放公开截图，不放付费源码
签到记录
piger 流水
解锁记录
分类
标签
```

## 后续升级方向

1. 开放投稿：把作品创建权限从管理员改为登录用户。
2. 投稿审核：给 Work 增加 review 状态。
3. 收藏和点赞：新建 favorite / like 表关联 work_id。
4. 评论：新建 comment 表关联 work_id。
5. 版本快照：为历史版本保留对应的源码文件。
6. 更多赚币方式：复用 PigerTransaction.reason。
