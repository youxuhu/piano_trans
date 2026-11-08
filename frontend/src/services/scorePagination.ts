export interface ScoreSystemBounds {
  top: number
  bottom: number
}

export interface ScorePage {
  firstSystem: number
  endSystem: number
  top: number
  bottom: number
}

/** Packs complete notation systems into viewport-height pages. */
export function paginateScoreSystems(
  systems: readonly ScoreSystemBounds[],
  pageHeight: number,
  firstPageHeight = pageHeight,
): ScorePage[] {
  if (!systems.length) return []
  const usableHeight = Math.max(1, pageHeight)
  const pages: ScorePage[] = []
  let firstSystem = 0
  let top = systems[0]!.top
  let bottom = systems[0]!.bottom

  for (let index = 1; index < systems.length; index++) {
    const system = systems[index]!
    const proposedBottom = system.bottom
    const pageCapacity = firstSystem === 0 ? Math.max(1, firstPageHeight) : usableHeight
    if (proposedBottom - top > pageCapacity && bottom > top) {
      pages.push({ firstSystem, endSystem: index, top, bottom })
      firstSystem = index
      top = system.top
      bottom = system.bottom
    } else {
      bottom = proposedBottom
    }
  }
  pages.push({ firstSystem, endSystem: systems.length, top, bottom })

  // The bounds include the vertical spacing between systems. An over-height
  // single system stays intact and the caller can scale that page to fit.
  return pages.map((page) => ({ ...page, bottom: Math.max(page.bottom, page.top + 1) }))
}

export function normalizeScoreDisplayTitle(title?: string | null, subtitle?: string | null) {
  const clean = (value?: string | null) => (value ?? '').replace(/_/g, ' ').trim()
  const normalizedTitle = clean(title)
  const normalizedSubtitle = clean(subtitle)
  return {
    title: normalizedTitle || '未命名曲目',
    subtitle: normalizedSubtitle && normalizedSubtitle !== normalizedTitle ? normalizedSubtitle : '',
  }
}
