import { AfterViewInit, Component, ElementRef, OnDestroy, effect, input, output, viewChild } from '@angular/core';
import * as L from 'leaflet';

/** OpenStreetMap site pin (§4 "site address with map"). Click to place the pin when editable. */
@Component({
  selector: 'app-map-picker',
  template: `<div #map class="map"></div>
    @if (editable()) { <small class="muted">Click the map to place the site pin.</small> }`,
  styles: `.map { height: 280px; border-radius: 12px; border: 1px solid var(--border); z-index: 0; }`,
})
export class MapPickerComponent implements AfterViewInit, OnDestroy {
  lat = input<number | null | undefined>();
  lng = input<number | null | undefined>();
  editable = input(false);
  picked = output<{ lat: number; lng: number }>();
  private el = viewChild.required<ElementRef<HTMLDivElement>>('map');
  private map?: L.Map;
  private pin?: L.CircleMarker;

  constructor() {
    effect(() => this.place(this.lat(), this.lng(), true));
  }

  ngAfterViewInit() {
    const has = this.lat() != null && this.lng() != null;
    this.map = L.map(this.el().nativeElement, { scrollWheelZoom: false }).setView(
      has ? [this.lat()!, this.lng()!] : [20.59, 78.96], has ? 15 : 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
    }).addTo(this.map);
    this.map.on('click', (e: L.LeafletMouseEvent) => {
      if (!this.editable()) return;
      const lat = +e.latlng.lat.toFixed(6);
      const lng = +e.latlng.lng.toFixed(6);
      this.place(lat, lng, false);
      this.picked.emit({ lat, lng });
    });
    this.place(this.lat(), this.lng(), true);
    setTimeout(() => this.map?.invalidateSize(), 200);
  }

  private place(lat: number | null | undefined, lng: number | null | undefined, recenter: boolean) {
    if (!this.map || lat == null || lng == null) return;
    if (!this.pin) this.pin = L.circleMarker([lat, lng], { radius: 9, color: '#4f46e5', fillColor: '#6366f1', fillOpacity: 0.9 }).addTo(this.map);
    else this.pin.setLatLng([lat, lng]);
    if (recenter) this.map.setView([lat, lng], Math.max(this.map.getZoom(), 15));
  }

  ngOnDestroy() {
    this.map?.remove();
  }
}
