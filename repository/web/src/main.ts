import {Component, signal} from '@angular/core';
import {bootstrapApplication} from '@angular/platform-browser';
import {FormsModule} from '@angular/forms';
import {api, User, Token} from './api';
import {initialLanguage, Language} from './i18n';

@Component({selector: 'app-root', standalone: true, imports: [FormsModule], templateUrl: './app.html'})
class App {
  language = signal<Language>(initialLanguage());
  accountPage = signal(location.pathname === '/account');
  installation = 'pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map';
  user = signal<User | null>(null);
  tokens = signal<Token[]>([]);
  newToken = signal('');
  notice = signal('');
  error = signal('');
  busy = signal(false);
  tokenLabel = '';
  tutorials = [
    {path: 'editor', fr: 'Créer une carte', en: 'Create a map', detailFr: 'Terrain 3D, forêts, bâtiments et remontées : votre première station avec l’éditeur.', detailEn: '3D terrain, forests, buildings and lifts: your first resort in the editor.'},
    {path: 'heightmap', fr: 'Importer un relief', en: 'Import terrain', detailFr: 'Transformez une heightmap R16 ou PNG 16 bits en montagne jouable.', detailEn: 'Turn an R16 or 16-bit PNG heightmap into a playable mountain.'},
    {path: 'scripts', fr: 'Écrire un scénario', en: 'Write a scenario', detailFr: 'Événements, objectifs et économie, avec des graphes ou du Lua.', detailEn: 'Events, goals and economy, with graphs or Lua.'},
    {path: 'mapmods', fr: 'Partager un mapmod', en: 'Share a mapmod', detailFr: 'Créez des comportements réutilisables sur plusieurs cartes.', detailEn: 'Create behaviours that work across multiple maps.'},
    {path: 'ticket-office', fr: 'Importer un modèle 3D', en: 'Import a 3D model', detailFr: 'Remplacez le Ticket Office et placez vos propres objets.', detailEn: 'Replace the Ticket Office and place your own objects.'},
  ];
  constructor() {
    this.setLanguage(this.language(), false);
    if (this.accountPage()) this.loadAccount();
    if (location.pathname === '/publish') location.replace('/#publier');
    window.addEventListener('popstate', () => {
      this.accountPage.set(location.pathname === '/account');
      if (this.accountPage()) this.loadAccount();
    });
  }
  t(fr: string, en: string) {return this.language() === 'fr' ? fr : en;}
  setLanguage(value: string, persist = true) {
    this.language.set(value === 'fr' ? 'fr' : 'en');
    document.documentElement.lang = this.language();
    document.title = this.t('SkiEO Mod — Créez votre montagne', 'SkiEO Mod — Create your mountain');
    document.querySelector('meta[name="description"]')?.setAttribute('content', this.t(
      'Installez SkiEO Mod, jouez aux cartes de la communauté dans Ski-E-O! et créez votre station avec nos tutoriels.',
      'Install SkiEO Mod, play community maps in Ski-E-O! and build your resort with our tutorials.'));
    if (persist) {try {localStorage.setItem('custom-map-language', this.language());} catch {}}
  }
  async loadAccount() {
    this.error.set('');
    try {
      this.user.set((await api<{user: User | null}>('/me')).user);
      if (this.user()) this.tokens.set((await api<{tokens: Token[]}>('/tokens')).tokens);
    } catch (error) {this.report(error);}
  }
  report(error: unknown) {this.error.set(error instanceof Error ? error.message : String(error));}
  async createToken() {
    const user = this.user(); if (!user || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {
      const result = await api<{token: string}>('/tokens', 'POST', {label: this.tokenLabel}, user.csrf);
      this.newToken.set(result.token); this.tokenLabel = ''; await this.loadAccount();
    } catch (error) {this.report(error);} finally {this.busy.set(false);}
  }
  async revoke(token: Token) {
    const user = this.user(); if (!user || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {await api('/tokens/' + token.id, 'DELETE', undefined, user.csrf); await this.loadAccount();}
    catch (error) {this.report(error);} finally {this.busy.set(false);}
  }
  async logout() {
    const user = this.user(); if (!user || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {await api('/logout', 'POST', undefined, user.csrf); this.user.set(null); this.tokens.set([]); this.newToken.set('');}
    catch (error) {this.report(error);} finally {this.busy.set(false);}
  }
  async copy(value: string) {
    try {await navigator.clipboard.writeText(value); this.notice.set(this.t('Copié.', 'Copied.'));}
    catch {this.notice.set(this.t('Sélectionnez le texte pour le copier.', 'Select the text to copy it.'));}
  }
}
bootstrapApplication(App).catch(console.error);
