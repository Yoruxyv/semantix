"""Static Lua programs for the Redis v1 cache protocol.

KEYS and ARGV layouts are shared with the Python call sites in redis.py; the
first six ARGV values are its ordered configuration descriptor. Keep script
bytes and composition unchanged during structural refactors: the checksum binds
_INITIALIZE + _READ + _WRITE to stored schemas, and _CLEAR_ALL derives from _WRITE.
Client lifecycle, argument validation and response decoding belong in redis.py.
"""

from hashlib import sha256

_COMMON = """
local meta, entries, lru = KEYS[1], KEYS[2], KEYS[3]
local names = {'marker','checksum','identity','dimensions','capacity','default_ttl'}
local function fail() error('Invalid Redis cache binding', 0) end
local function types()
    local expected = {'hash','hash','zset'}
    for i=1,3 do
        local t = redis.call('TYPE', KEYS[i]).ok
        if t ~= 'none' and t ~= expected[i] then fail() end
        if redis.call('PTTL', KEYS[i]) >= 0 then fail() end
    end
end
local function schema()
    types()
    if redis.call('HLEN',meta)~=9 then fail() end
    for i,name in ipairs(names) do
        if redis.call('HGET', meta, name) ~= ARGV[i] then fail() end
    end
    if redis.call('HGET', meta, 'status') ~= 'ready' then fail() end
    if redis.call('ZCARD', lru) > tonumber(ARGV[5]) then fail() end
end
"""

_DATA = """
local function uint(s)
    if type(s) ~= 'string' or not string.match(s, '^%d+$') or
       (#s > 1 and string.sub(s,1,1) == '0') then fail() end
    return s
end
local function cmp(a,b)
    local an,bn = string.sub(a,1,1)=='-',string.sub(b,1,1)=='-'
    if an ~= bn then return an and -1 or 1 end
    local aa,bb = an and string.sub(a,2) or a,bn and string.sub(b,2) or b
    local c = 0
    if #aa ~= #bb then c = #aa < #bb and -1 or 1
    elseif aa ~= bb then c = aa < bb and -1 or 1 end
    return an and -c or c
end
local function revision(s)
    if type(s) ~= 'string' or s == '-0' then fail() end
    uint(string.sub(s,1,1)=='-' and string.sub(s,2) or s)
    if cmp(s,'-62135596800000000') < 0 or cmp(s,'253402300799999999') > 0 then fail() end
    return s
end
local function add(a,b)
    uint(a); uint(b)
    local out,carry = '',0
    local i,j = #a,#b
    while i>0 or j>0 or carry>0 do
        local x = i>0 and tonumber(string.sub(a,i,i)) or 0
        local y = j>0 and tonumber(string.sub(b,j,j)) or 0
        local sum = x+y+carry
        out = tostring(sum%10)..out
        carry = math.floor(sum/10)
        i=i-1; j=j-1
    end
    return out
end
local function clock()
    local t = redis.call('TIME')
    return t[1]..string.rep('0',6-#t[2])..t[2]
end
local function millis(e)
    local ms = string.sub(e,1,#e-3)
    if string.sub(e,-3) ~= '000' then ms=add(ms,'1') end
    return ms
end
local function member(m)
    local ns,key = string.match(m,'^([^|]+)|([a-f0-9]+)$')
    if not ns or #ns>64 or not string.match(ns,'^[A-Za-z0-9][A-Za-z0-9._:-]*$') or #key~=64 then fail() end
    return ns,key
end
local function fields(m)
    return {m..':p',m..':v',m..':r',m..':e',m..':h',m..':a'}
end
local function item(m,now)
    member(m)
    local values = redis.call('HMGET',entries,m..':r',m..':e',m..':h',m..':a')
    local r,e,h,a = values[1],values[2],values[3],values[4]
    if e and e~='' then
        uint(e); revision(e)
        if cmp(e,now)<=0 then return nil end
    end
    if not r and not e and not h and not a then
        if redis.call('HEXISTS',entries,m..':p')~=0 or redis.call('HEXISTS',entries,m..':v')~=0 then fail() end
        return nil
    end
    revision(r)
    if not e or not h or not a then fail() end
    uint(h)
    if cmp(h,'9223372036854775807')>0 then fail() end
    if a~='' then uint(a); revision(a) end
    if redis.call('HSTRLEN',entries,m..':v')~=tonumber(ARGV[4])*8 or
       redis.call('HSTRLEN',entries,m..':p')<2 or
       redis.call('HSTRLEN',entries,m..':p')>1230000 then fail() end
    return values
end
local function state()
    schema()
    local last=redis.call('HGET',meta,'last_revision_us')
    if not last then fail() end
    if last~='' then revision(last) end
    local count=uint(redis.call('HGET',meta,'access_counter'))
    if cmp(count,'9007199254740991')>0 then fail() end
    if redis.call('HLEN',entries)>tonumber(ARGV[5])*6 then fail() end
    for _,field in ipairs(redis.call('HKEYS',entries)) do
        local m=string.match(field,'^(.*):[pvreha]$')
        if not m or not redis.call('ZSCORE',lru,m) then fail() end
        member(m)
    end
    return last,tonumber(count)
end
local function members()
    local ranked=redis.call('ZRANGE',lru,0,-1,'WITHSCORES')
    local result,prior={},0
    local count=tonumber(redis.call('HGET',meta,'access_counter'))
    for i=1,#ranked,2 do
        local score=tonumber(ranked[i+1])
        if not score or score<=prior or score>count or score%1~=0 then fail() end
        prior=score
        member(ranked[i])
        result[#result+1]=ranked[i]
    end
    return result
end
"""

_READ = (
    _COMMON
    + _DATA
    + """
state()
local now=clock()
local op=ARGV[7]
if op=='validate' then
    for _,m in ipairs(members()) do item(m,now) end
    return 1
end
if op=='snapshot' then
    local result={}
    for _,m in ipairs(members()) do
        if member(m)==ARGV[8] then
            local values=item(m,now)
            if values then
                result[#result+1]={m,values[1],values[2],redis.call('HGET',entries,m..':v')}
            end
        end
    end
    return result
end
if op=='winner' then
    local m=ARGV[8]
    local values=item(m,now)
    if not values or values[1]~=ARGV[9] then return false end
    if not redis.call('ZSCORE',lru,m) then fail() end
    return {redis.call('HGET',entries,m..':p'),redis.call('HGET',entries,m..':v'),values[1],values[2]}
end
fail()
"""
)

_WRITE = (
    _COMMON
    + _DATA
    + """
local last,count=state()
local ranked=members()
local now=clock()
local op,m=ARGV[7],ARGV[8]
local current,all,expired={}, {}, {}
if op=='put' or op=='clear' then
    all=ranked
    for _,key in ipairs(all) do
        current[key]=item(key,now)
        if not current[key] then expired[#expired+1]=key end
    end
elseif op=='hit' or op=='delete' then
    current[m]=item(m,now)
    if current[m] and not redis.call('ZSCORE',lru,m) then fail() end
else fail() end
if op=='hit' then
    if not current[m] or current[m][1]~=ARGV[9] then return 0 end
    if current[m][3]=='9223372036854775807' then fail() end
end
local expiry=''
if op=='put' then
    member(m)
    revision(ARGV[9])
    if last=='253402300799999999' then fail() end
    if ARGV[10]~='' then expiry=add(now,uint(ARGV[10])); revision(expiry) end
    if #ARGV[11]<2 or #ARGV[11]>1230000 or #ARGV[12]~=tonumber(ARGV[4])*8 then fail() end
end
local function permit(command,key,...)
    if not redis.acl_check_cmd(command,key,...) then fail() end
end
permit('HSET',meta,'status','mutating')
permit('HDEL',entries,'preflight')
permit('ZREM',lru,'preflight')
if op=='put' or op=='hit' then
    permit('HSET',meta,'access_counter','1')
    permit('ZADD',lru,'1',m)
    permit('HSET',entries,m..':a',now)
    if op=='put' then
        permit('HINCRBY',meta,'last_revision_us',1)
        permit('HSET',entries,m..':p',ARGV[11])
    else permit('HINCRBY',entries,m..':h',1) end
    local e=op=='put' and expiry or current[m][2]
    if e~='' then permit('HPEXPIREAT',entries,millis(e),'FIELDS',1,m..':a') end
end
redis.call('HSET',meta,'status','mutating')
local function remove(key)
    redis.call('HDEL',entries,unpack(fields(key)))
    redis.call('ZREM',lru,key)
end
local function rank()
    if count>=9007199254740990 then
        local ordered=redis.call('ZRANGE',lru,0,-1)
        for i,key in ipairs(ordered) do redis.call('ZADD',lru,i,key) end
        count=#ordered
    end
    count=count+1
    redis.call('HSET',meta,'access_counter',string.format('%.0f',count))
    return count
end
local result=0
if op=='put' then
    for _,key in ipairs(expired) do remove(key) end
    local r=ARGV[9]
    if last~='' and cmp(r,last)<=0 then
        redis.call('HINCRBY',meta,'last_revision_us',1)
        r=redis.call('HGET',meta,'last_revision_us')
    else redis.call('HSET',meta,'last_revision_us',r) end
    redis.call('HSET',entries,m..':p',ARGV[11],m..':v',ARGV[12],m..':r',r,m..':e',expiry,m..':h','0',m..':a','')
    redis.call('ZADD',lru,rank(),m)
    if expiry~='' then
        redis.call('HPEXPIREAT',entries,millis(expiry),'FIELDS',6,unpack(fields(m)))
        if cmp(expiry,now)<=0 then remove(m) end
    end
    while redis.call('ZCARD',lru)>tonumber(ARGV[5]) do
        remove(redis.call('ZRANGE',lru,0,0)[1])
    end
elseif op=='hit' then
    redis.call('HINCRBY',entries,m..':h',1)
    redis.call('HSET',entries,m..':a',now)
    redis.call('ZADD',lru,rank(),m)
    local e=current[m][2]
    if e~='' then redis.call('HPEXPIREAT',entries,millis(e),'FIELDS',1,m..':a') end
    result=1
elseif op=='delete' then
    result=current[m] and 1 or 0
    remove(m)
elseif op=='clear' then
    for _,key in ipairs(all) do
        if member(key)==m then
            if current[key] then result=result+1 end
            remove(key)
        end
    end
end
redis.call('HSET',meta,'status','ready')
return result
"""
)

_INITIALIZE = (
    _COMMON
    + _DATA
    + """
types()
if redis.call('EXISTS',meta)==1 then
    state()
    local now=clock()
    for _,m in ipairs(members()) do item(m,now) end
    return 0
end
if redis.call('EXISTS',entries,lru)~=0 then fail() end
local fields={}
for i,name in ipairs(names) do fields[#fields+1]=name; fields[#fields+1]=ARGV[i] end
fields[#fields+1]='last_revision_us'; fields[#fields+1]=''
fields[#fields+1]='access_counter'; fields[#fields+1]='0'
fields[#fields+1]='status'; fields[#fields+1]='ready'
redis.call('HSET',meta,unpack(fields))
return 1
"""
)

_CHECKSUM = sha256((_INITIALIZE + _READ + _WRITE).encode()).hexdigest()

# Optional administration retains the accepted descriptor and original scripts.
# The wildcard is inaccessible through CacheStore.clear(), which validates namespaces.
_CLEAR_ALL = _WRITE.replace("if member(key)==m then", "if true then")
_INSPECT = (
    _COMMON
    + _DATA
    + """
state()
local now=clock()
local ranked=members()
local eligible={}
local scope=ARGV[7]
local key=ARGV[8]
local allowed=cjson.decode(ARGV[9])
local rank=0
for i=#ranked,1,-1 do
    local m=ranked[i]
    local ns,k=member(m)
    local permitted=ARGV[9]=='null'
    if not permitted then for _,n in ipairs(allowed) do if n==ns then permitted=true end end end
    if (scope=='' or scope==ns) and permitted then
        local values=item(m,now)
        if values then
            rank=rank+1
            if key=='' or key==k then
                eligible[#eligible+1]={m,values,tostring(rank),k,ns}
            end
        end
    end
end
local sort=ARGV[12]
table.sort(eligible,function(a,b)
    local av,bv=a[2],b[2]
    if sort=='most_hit' and av[3]~=bv[3] then return cmp(av[3],bv[3])>0 end
    if sort=='nearest_expiry' and av[2]~=bv[2] then
        if av[2]=='' then return false end
        if bv[2]=='' then return true end
        return cmp(av[2],bv[2])<0
    end
    if av[1]~=bv[1] then
        if sort=='oldest' then return cmp(av[1],bv[1])<0 end
        return cmp(av[1],bv[1])>0
    end
    if a[4]~=b[4] then return a[4]<b[4] end
    return a[5]<b[5]
end)
local result={}
local offset=tonumber(ARGV[10])
local limit=tonumber(ARGV[11])
for i=offset+1,math.min(#eligible,offset+limit) do
    local row=eligible[i]
    local m,values=row[1],row[2]
    local p=cjson.decode(redis.call('HGET',entries,m..':p'))
    if p.cache_key~=row[4] or p.namespace~=row[5] or type(p.prompt)~='string' or type(p.response)~='string' then fail() end
    local chars=0
    local finish=#p.response
    for j=1,#p.response do
        local b=string.byte(p.response,j)
        if b<128 or b>=192 then chars=chars+1 end
        if chars>240 then finish=j-1; break end
    end
    local response=key=='' and '' or p.response
    result[#result+1]={m,p.prompt,response,string.sub(p.response,1,finish),values[1],values[2],values[3],values[4],row[3],now,chars>240 and '1' or '0'}
end
return {#eligible,result}
"""
)
