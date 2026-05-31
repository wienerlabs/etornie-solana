'use client';

import StaggeredMenu, {
  type StaggeredMenuItem,
  type StaggeredMenuSocialItem,
} from './StaggeredMenu';

// Landing navigation, mapped to the existing top-nav links.
const MENU_ITEMS: StaggeredMenuItem[] = [
  { label: 'Home', ariaLabel: 'Go to the home page', link: '/' },
  { label: 'Product', ariaLabel: 'See the product', link: '/#product' },
  { label: 'RWA', ariaLabel: 'Real-world assets', link: '/#rwa' },
  { label: 'Enterprise', ariaLabel: 'Enterprise features', link: '/#enterprise' },
  { label: 'Docs', ariaLabel: 'Read the documentation', link: '/docs' },
  { label: 'Sign In', ariaLabel: 'Sign in to your dashboard', link: '/login' },
  { label: 'Get Started', ariaLabel: 'Create an account', link: '/register' },
];

// TODO: replace with Etornie's real handles when available.
const SOCIAL_ITEMS: StaggeredMenuSocialItem[] = [
  { label: 'GitHub', link: 'https://github.com/wienerlabs' },
  { label: 'X', link: 'https://x.com/etornie' },
  { label: 'LinkedIn', link: 'https://www.linkedin.com/company/etornie' },
];

// Etornie brand blue (globals.css --color-accent #2520FE).
const BRAND_BLUE = '#2520FE';
const BRAND_BLUE_LIGHT = '#5B57FF';

export default function SiteMenu() {
  return (
    <StaggeredMenu
      position="right"
      isFixed
      items={MENU_ITEMS}
      socialItems={SOCIAL_ITEMS}
      displaySocials
      displayItemNumbering
      logoUrl="/etornie-logo.png"
      colors={[BRAND_BLUE_LIGHT, BRAND_BLUE]}
      accentColor={BRAND_BLUE}
      menuButtonColor={BRAND_BLUE}
      openMenuButtonColor="#0A0A0A"
      changeMenuColorOnOpen
    />
  );
}
