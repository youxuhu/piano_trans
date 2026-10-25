// Naive UI 主题覆盖 —— 暖木·米白
// 主色沿用用户偏好的绿系（松绿），点缀暖木色，营造"演奏厅/暖木纸卷"氛围
export const themeOverrides = {
  common: {
    primaryColor: '#5E7A5A',
    primaryColorHover: '#6D8C68',
    primaryColorPressed: '#4F6A4B',
    primaryColorSuppl: '#5E7A5A',
    successColor: '#5E7A5A',
    infoColor: '#7A8B6E',
    warningColor: '#C08A3E',
    errorColor: '#B4553F',
    textColorBase: '#2E2A24',
    textColor1: '#2E2A24',
    textColor2: '#4C4539',
    textColor3: '#8A8072',
    bodyColor: '#FAF6EE',
    cardColor: '#FFFFFF',
    modalColor: '#FFFFFF',
    popoverColor: '#FFFFFF',
    borderRadius: '10px',
    borderRadiusSmall: '8px',
    borderColor: '#E7DECB',
    dividerColor: '#ECE4D3',
    placeholderColor: '#A99F8E',
    fontFamily:
      "'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', system-ui, -apple-system, sans-serif",
    fontFamilyMono:
      "'Cascadia Code', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
  },
  Button: {
    borderRadiusMedium: '10px',
    fontWeight: '600',
  },
  Slider: {
    railColor: '#E7DECB',
    railColorHover: '#DDD2BC',
    fillColor: '#5E7A5A',
    fillColorHover: '#6D8C68',
  },
  Input: {
    borderRadius: '10px',
  },
  Card: {
    borderRadius: '16px',
  },
  // 顶栏与面板常用
  Layout: {
    color: '#FAF6EE',
    siderColor: '#F3ECDD',
    headerColor: '#2F3E30',
    headerColorModal: '#2F3E30',
  },
}