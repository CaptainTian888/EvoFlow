/**
 * 员工(智能体岗位)展示名解析 —— 全局唯一 SoT。
 *
 * 数据源:
 *   - `GET /api/proactive/roles`         → 雇佣了的角色,带 `role_name`(岗位名)
 *   - `GET /api/agents`                  → 所有智能体,带 `agent_name`(智能体名)
 *
 * 设计意图(后端 schema):
 *   `evoflow_proactive_roles.role_name` 是 NOT NULL,每个雇佣岗位必须有岗位名。
 *   老 DB 里若有空字符串,是历史脏数据,本工具不做回填,只把 UI 显示兜底到 `agent_name`。
 *
 * 之前以下 4 处各写了一份 fallback / 归一化逻辑,语义漂移严重:
 *   - evopanel/src/react/components/ShellSessionList.tsx       (员工 Tab 下拉/分组标题)
 *   - evopanel/src/react/ChatApp.tsx                           (@ 员工菜单 proactiveRolesDisplay)
 *   - evopanel/src/pages/proactive.js                          (proactive 卡片 roleCardTitle)
 *   - evopanel/src/react/components/ChatWorkspaceInfoRail.tsx (右侧员工详情 roleName)
 *
 * 统一到本模块,调用方一律:
 *   resolveEmployeeDisplayName(code, { roles, agents })
 */

export type EmployeeRoleLike = {
  agent_code?: string | null
  /** 岗位名 / 角色名(中文,优先显示)。可能为 null/空(历史脏数据)。 */
  role_name?: string | null
  /** 智能体名(中文,可来自 evoflow_proactive_roles.agent_name 或 /api/agents.agent_name)。 */
  agent_name?: string | null
}

export type AgentMetaLike = {
  agent_code?: string | null
  agent_name?: string | null
}

export type EmployeeDisplaySources = {
  /** `GET /api/proactive/roles` 的列表(或经过派生的 dict)。 */
  roles?: ReadonlyArray<EmployeeRoleLike> | null
  /** `GET /api/agents` 的列表,用于补充 agent_name。类型故意保持宽松,内部按需断言。 */
  agents?: ReadonlyArray<unknown> | null
  /** 直接提供该 code 对应的智能体名(例如来自父级传下来的已解析值),优先于上面的 agents 查找。 */
  agentNameHint?: string | null
}

/** 整组常量「智能体员工」不是具体岗位名,不能当下拉项文案。 */
export const EMPLOYEE_GENERIC_GROUP_LABEL = '智能体员工'

/** 统一规范化:忽略大小写,_/- 互通,避免匹配失败后露出英文 code。 */
export function normalizeEmployeeCodeKey(code: string): string {
  return String(code || '')
    .trim()
    .toLowerCase()
    .replace(/_/g, '-')
}

/**
 * label 是否是「整组常量」(`智能体员工` / 空 / 与 code 折叠),不能当岗位名。
 */
export function isGenericEmployeeLabel(value: string): boolean {
  const t = String(value || '').trim()
  return !t || t === EMPLOYEE_GENERIC_GROUP_LABEL
}

/**
 * 岗位名是否已塌成英文 agent_code(数据脏,空字符串或与 code 等价)。
 * 返回 true 表示该 label 不能当岗位名使用。
 */
export function isCollapsedJobTitle(title: string, agentCode: string): boolean {
  const name = String(title || '').trim()
  if (!name) return true
  const code = String(agentCode || '').trim()
  if (!code) return false
  return normalizeEmployeeCodeKey(name) === normalizeEmployeeCodeKey(code)
}

/**
 * 在 sources.roles 中查找匹配 agent_code 的角色记录(大小写/分隔符不敏感)。
 */
function findRole(
  code: string,
  roles: ReadonlyArray<EmployeeRoleLike> | null | undefined,
): EmployeeRoleLike | undefined {
  const codeKey = normalizeEmployeeCodeKey(code)
  if (!codeKey || !Array.isArray(roles)) return undefined
  return roles.find((r) => normalizeEmployeeCodeKey(r.agent_code || '') === codeKey)
}

/**
 * 在 sources.agents 中查找匹配 agent_code 的智能体记录(大小写/分隔符不敏感)。
 * agents 故意声明为 ReadonlyArray<unknown>,因为不同上游(ShellSessionList 等)传的是
 * unknown[];此处内部断言为 AgentMetaLike。
 */
function findAgent(
  code: string,
  agents: ReadonlyArray<unknown> | null | undefined,
): AgentMetaLike | undefined {
  const codeKey = normalizeEmployeeCodeKey(code)
  if (!codeKey || !Array.isArray(agents)) return undefined
  return agents.find((a) => normalizeEmployeeCodeKey(String((a as AgentMetaLike)?.agent_code || '')) === codeKey) as
    | AgentMetaLike
    | undefined
}

/**
 * 解析员工岗位展示名 —— 全局唯一入口。
 *
 * 优先级:
 *   1. role.role_name(非空、未塌成 code、未与整组常量冲突)
 *   2. agentNameHint(父级已解析好的智能体名)
 *   3. role.agent_name(岗位行里的智能体名)
 *   4. agents[].agent_name(`/api/agents` 列表里的智能体名)
 *   5. '' (空串 —— 调用方决定是否再 fallback 到 code 或显示「智能体员工」)
 *
 * 永远不返回「未命名岗位」字面量,绝不将 agent_name 回填写入 role_name。
 */
export function resolveEmployeeDisplayName(
  agentCode: string,
  sources: EmployeeDisplaySources = {},
): string {
  const code = String(agentCode || '').trim()
  const role = findRole(code, sources.roles)
  const codeKey = normalizeEmployeeCodeKey(code)

  // 1. role_name(原始岗位名)
  const roleName = String(role?.role_name || '').trim()
  if (roleName && !isGenericEmployeeLabel(roleName) && !isCollapsedJobTitle(roleName, code)) {
    return roleName
  }

  // 2. 父级 hint
  const hint = String(sources.agentNameHint || '').trim()
  if (hint && !isGenericEmployeeLabel(hint) && !isCollapsedJobTitle(hint, code)) {
    return hint
  }

  // 3. role.agent_name
  const roleAgentName = String(role?.agent_name || '').trim()
  if (roleAgentName && !isGenericEmployeeLabel(roleAgentName) && !isCollapsedJobTitle(roleAgentName, code)) {
    return roleAgentName
  }

  // 4. /api/agents 列表
  const agent = findAgent(code, sources.agents)
  const agentName = String(agent?.agent_name || '').trim()
  if (agentName && !isGenericEmployeeLabel(agentName) && !isCollapsedJobTitle(agentName, code)) {
    return agentName
  }

  return ''
}

/**
 * 同 resolveEmployeeDisplayName,但当所有 fallback 都拿不到时,返回 code 而非空串。
 * 适用于「必须有展示文案」的列表行(`<span>` 不能空着)。
 */
export function resolveEmployeeDisplayNameWithCode(
  agentCode: string,
  sources: EmployeeDisplaySources = {},
): string {
  const resolved = resolveEmployeeDisplayName(agentCode, sources)
  if (resolved) return resolved
  return String(agentCode || '').trim()
}

/**
 * 给定一组 role 行(常见于 proactiveListRoles),批量预填 agent_name(从 agents 列表补全),
 * 返回新的数组(不修改入参)。纯函数。
 *
 * 用途: `@ 员工` 下拉需要稳定的中文展示名,但 proactive 接口并不一定带 agent_name,
 * 所以前端用 `/api/agents` 列表做一次 join 兜底。
 */
export function enrichRolesWithAgentNames<
  T extends EmployeeRoleLike & { department?: string | null; status?: string | null },
>(roles: ReadonlyArray<T> | null | undefined, agents: ReadonlyArray<unknown> | null | undefined): T[] {
  if (!Array.isArray(roles) || roles.length === 0) return []
  const codeToName = new Map<string, string>()
  if (Array.isArray(agents)) {
    for (const a of agents) {
      const code = normalizeEmployeeCodeKey(a.agent_code || '')
      const name = String(a.agent_name || '').trim()
      if (code && name && !codeToName.has(code)) codeToName.set(code, name)
    }
  }
  return roles.map((r) => {
    const code = normalizeEmployeeCodeKey(r.agent_code || '')
    const filled = String(r.agent_name || '').trim() || codeToName.get(code) || ''
    if (filled === String(r.agent_name || '').trim()) return r
    return { ...r, agent_name: filled }
  })
}