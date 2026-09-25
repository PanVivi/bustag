% rebase('base.tpl', title='V2 数据维护', path=path)
<div class="container">
<a href="/tagit">返回原版打标页</a>
<details><summary>经人工核实，合并同一人的网站身份</summary>
<form method="post" action="/v2/merge-actor"><input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="return_to" value="/v2/manage?page={{page}}">
<label>原演员 ID <input name="source_actor" required></label>
<label>目标演员 ID <input name="target_actor" required></label><button>确认同一演员</button></form>
<p>仅相同姓名不足以合并。有矛盾人工偏好时需先由用户处理。</p></details>
<h5>标签来源与语义映射</h5>
% for tag in tags:
<form method="post" action="/v2/map-tag">
<input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="return_to" value="/v2/manage?page={{page}}">
% for key in ['source','category','source_id']:
<input type="hidden" name="{{key}}" value="{{tag[key]}}">
% end
<p>{{tag['source']}} / {{tag['category']}} / {{tag['name']}} → {{tag['canonical_category']}} / {{tag['canonical_name']}} · {{'人工核实' if tag['verified'] else '未核实'}}</p>
<label>规范标签 ID <input name="tag_id" value="{{tag['tag_id']}}" required></label><button>确认语义映射</button>
</form>
% end
<h5>待确认媒体副本</h5>
% for media in pending:
<form method="post" action="/v2/resolve-media"><input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="return_to" value="/v2/manage?page={{page}}">
% for key in ['server','item_id']:
<input type="hidden" name="{{key}}" value="{{media[key]}}">
% end
{{media['item_id']}} <label>确认作品 ID <input name="work_id" required></label><button>确认对应作品</button></form>
% end
<p>本页仅用于高级身份/标签映射维护；日常打标与演员偏好请在原版标签卡片中操作。Emby 核对仅限私有只读范围，页面不公开媒体路径。</p>
% if page > 1:
<a href="/v2/manage?page={{page-1}}">上一页</a>
% end
<a href="/v2/manage?page={{page+1}}">下一页</a>
</div>
