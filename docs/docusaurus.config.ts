import { themes as prismThemes } from 'prism-react-renderer';
import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'BirdXplorer Documentation',
  tagline: 'BirdXplorer is software that helps users explore community notes data on X (formerly known as Twitter).',
  favicon: 'img/favicon.ico',

  url: 'https://github.com/',
  baseUrl: '/codeforjapan/BirdXplorer/',

  organizationName: 'codeforjapan',
  projectName: 'BirdXplorer',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'ja'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
        },
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/birdxplorer-social-card.jpg',
    navbar: {
      title: 'BirdXplorer Documentation',
      logo: {
        alt: 'BirdXplorer Logo',
        src: 'img/logo.png',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          href: 'https://github.com/codeforjapan/BirdXplorer',
          className: 'header-github-link',
          'aria-label': 'GitHub repository',
          position: 'right',
          label: 'GitHub',
        },
      ],
    },
    footer: {
      style: 'dark',
      copyright: `Copyright © ${new Date().getFullYear()} Code for Japan. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
