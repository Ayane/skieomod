export type Language = 'fr' | 'en';
export function initialLanguage(): Language {
  try {
    const saved = localStorage.getItem('custom-map-language');
    if (saved === 'fr' || saved === 'en') return saved;
  } catch {}
  return navigator.language.toLowerCase().startsWith('fr') ? 'fr' : 'en';
}
