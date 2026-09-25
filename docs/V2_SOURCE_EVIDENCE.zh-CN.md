# 外部来源核查记录

核查日期：2026-09-22。本记录只描述本轮实际获得的证据。

## JavDB

访问 `https://javdb.com/`：抓取工具返回 HTTP 403 Forbidden，未获得影片详情页面。
因此没有可验证的分类 ID、真实分类全集、不同影片类型字段样本或缺失案例。
不编造选择器，不使用未经核查的分流域名，不声称 JavDB 适配已验收。
目前多来源数据结构、语义映射及纠错可测试，但真实 JavDB 抓取未启用。
后续须提供合法可访问的页面或脱敏保存的 HTML，并记录访问时间、原始分类/标签 ID、
不同影片样本和缺失案例，再实现/验证适配器。爬取失败不得删除已有记录。

## Emby

核对官方文档：

- [ItemsService /Users/{UserId}/Items](https://dev.emby.media/reference/RestAPI/ItemsService/getUsersByUseridItems.html)
- [Browsing the Library](https://dev.emby.media/doc/restapi/Browsing-the-Library.html)

实现使用限定 UserId、ParentId 的 GET 查询，分页 StartIndex/Limit，取得 ProviderIds、
People、Path、Genres、MediaSources、OriginalTitle 和 UserData。只 GET，不调用媒体写接口。
秘密只读私有环境变量，置于请求头，禁止跟随重定向携带凭据；测试使用合成响应。
没有连接用户 Emby，实际服务版本支持的字段、可播放状态、网页跳转和同步时片库变动
仍需在授权后实测。服务器不可达保留成功快照并标过期，本地推荐停止采用过期可播放判断。
