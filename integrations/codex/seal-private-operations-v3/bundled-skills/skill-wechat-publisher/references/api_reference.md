# 微信公众号 API 接口参考

本文档列出了发布文章流程中涉及的所有微信API接口，方便快速查阅。

## 1. 获取 Access Token

- **URL**: `https://api.weixin.qq.com/cgi-bin/token`
- **方法**: GET
- **参数**:
  - `grant_type`: 固定值 `client_credential`
  - `appid`: 公众号的AppID
  - `secret`: 公众号的AppSecret
- **返回值**:
  ```json
  {"access_token": "ACCESS_TOKEN", "expires_in": 7200}
  ```
- **注意**: token有效期2小时，需要缓存和自动刷新；IP白名单必须配置

## 2. 上传永久素材（封面图）

- **URL**: `https://api.weixin.qq.com/cgi-bin/material/add_material?access_token=ACCESS_TOKEN&type=image`
- **方法**: POST (multipart/form-data)
- **参数**: `media` - 图片文件
- **限制**: 图片大小不超过10MB，支持 jpg/png/gif/bmp
- **返回值**:
  ```json
  {"media_id": "MEDIA_ID", "url": "URL"}
  ```
- **用途**: 获取封面图的 `media_id`，用于创建草稿时的 `thumb_media_id`

## 3. 上传正文图片

- **URL**: `https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token=ACCESS_TOKEN`
- **方法**: POST (multipart/form-data)
- **参数**: `media` - 图片文件
- **限制**: 图片大小不超过10MB
- **返回值**:
  ```json
  {"url": "https://mmbiz.qpic.cn/..."}
  ```
- **用途**: 获取微信CDN图片URL，嵌入文章HTML正文中。此接口上传的图片不占用永久素材名额。

## 4. 新建草稿

- **URL**: `https://api.weixin.qq.com/cgi-bin/draft/add?access_token=ACCESS_TOKEN`
- **方法**: POST (application/json)
- **请求体**:
  ```json
  {
    "articles": [
      {
        "title": "文章标题",
        "author": "作者",
        "digest": "摘要（不超过120字）",
        "content": "HTML正文内容",
        "content_source_url": "原文链接",
        "thumb_media_id": "封面图的media_id",
        "need_open_comment": 1,
        "only_fans_can_comment": 0
      }
    ]
  }
  ```
- **返回值**:
  ```json
  {"media_id": "DRAFT_MEDIA_ID"}
  ```
- **注意**:
  - `content` 中的图片必须使用微信CDN的URL（通过uploadimg接口获取）
  - 编码必须使用 `ensure_ascii=False` 避免中文乱码
  - 单次最多8篇文章

## 5. 发布草稿（可选）

- **URL**: `https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token=ACCESS_TOKEN`
- **方法**: POST
- **请求体**:
  ```json
  {"media_id": "DRAFT_MEDIA_ID"}
  ```
- **返回值**: 发布任务ID
- **注意**: 建议在公众平台手动确认发布，避免误操作

## 常见错误码

| 错误码 | 说明 | 解决方法 |
|--------|------|----------|
| 40001 | access_token无效 | 重新获取token |
| 40002 | 不合法的凭证类型 | 检查AppID/AppSecret |
| 40004 | 不合法的媒体文件类型 | 检查图片格式 |
| 40009 | 图片大小超限 | 压缩到10MB以内 |
| 40014 | 不合法的access_token | 刷新token |
| 45009 | 接口调用超限 | 降低调用频率 |
| 48001 | 接口未授权 | 检查公众号权限 |
| 40164 | IP不在白名单中 | 在公众平台添加IP白名单 |

## API调用频率限制

- access_token获取：每日2000次
- 素材上传：每日100次
- 草稿操作：每日100次
- 建议合理缓存token，避免频繁调用
