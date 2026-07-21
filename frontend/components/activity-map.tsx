"use client";

import * as React from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useTheme } from "next-themes";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const LIGHT_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const DARK_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

// The --accent CSS var holds space-separated HSL components; MapLibre wants comma syntax.
function accentColor(el: HTMLElement): string {
  const v = getComputedStyle(el).getPropertyValue("--accent").trim();
  return v ? `hsl(${v.split(/\s+/).join(", ")})` : "#ea580c";
}

function dotMarker(color: string): HTMLElement {
  const el = document.createElement("div");
  el.style.cssText = `width:14px;height:14px;border-radius:9999px;background:${color};border:3px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.4);`;
  return el;
}

function addRouteLayers(
  map: maplibregl.Map,
  coords: Array<[number, number]>,
  dark: boolean,
  accent: string,
) {
  map.addSource("route", {
    type: "geojson",
    data: {
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: coords },
    },
  });
  map.addLayer({
    id: "route-casing",
    type: "line",
    source: "route",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": dark ? "#000000" : "rgba(24, 24, 27, 0.35)", "line-width": 6 },
  });
  map.addLayer({
    id: "route-line",
    type: "line",
    source: "route",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": accent, "line-width": 3.5 },
  });
}

/** A [[lat, lon], ...] polyline on a Carto basemap, themed with the app.
 *  Bare map (no card) so races and dialogs can embed it too. */
export function RouteMap({
  route,
  className,
}: {
  route: Array<[number, number]>;
  className?: string;
}) {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mapRef = React.useRef<maplibregl.Map | null>(null);
  const appliedStyleRef = React.useRef<string | null>(null);
  const darkRef = React.useRef(dark);
  darkRef.current = dark;

  // API sends [lat, lon]; GeoJSON wants [lon, lat].
  const coords = React.useMemo(
    () => route.map(([lat, lon]) => [lon, lat] as [number, number]),
    [route],
  );

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container || coords.length < 2) return;

    const initialStyle = darkRef.current ? DARK_STYLE : LIGHT_STYLE;
    appliedStyleRef.current = initialStyle;
    const map = new maplibregl.Map({
      container,
      style: initialStyle,
      cooperativeGestures: true,
      attributionControl: false,
    });
    // The Carto style already carries "© CARTO, © OpenStreetMap contributors";
    // no customAttribution or it shows twice. Compact mode starts EXPANDED by
    // design, so collapse it once rendered - the "i" button keeps the credits
    // one tap away, which satisfies the OSM attribution requirement.
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.once("load", () => {
      const attrib = container.querySelector(".maplibregl-ctrl-attrib");
      attrib?.classList.remove("maplibregl-compact-show");
      attrib?.removeAttribute("open");
    });

    // Fires on initial load and after every setStyle; layers must be re-added each time.
    map.on("style.load", () => {
      addRouteLayers(map, coords, darkRef.current, accentColor(container));
    });

    // Markers are DOM overlays, so they survive style swaps.
    new maplibregl.Marker({ element: dotMarker("#16a34a") }).setLngLat(coords[0]).addTo(map);
    new maplibregl.Marker({ element: dotMarker("#dc2626") })
      .setLngLat(coords[coords.length - 1])
      .addTo(map);

    const bounds = coords.reduce(
      (b, c) => b.extend(c),
      new maplibregl.LngLatBounds(coords[0], coords[0]),
    );
    map.fitBounds(bounds, { padding: 40, animate: false });

    mapRef.current = map;
    return () => {
      mapRef.current = null;
      map.remove();
    };
  }, [coords]);

  React.useEffect(() => {
    const style = dark ? DARK_STYLE : LIGHT_STYLE;
    // Skip the mount run (and any no-op): setStyle re-fetches even for the same URL.
    if (mapRef.current && appliedStyleRef.current !== style) {
      appliedStyleRef.current = style;
      mapRef.current.setStyle(style);
    }
  }, [dark]);

  return (
    <div
      ref={containerRef}
      className={cn("h-64 w-full overflow-hidden rounded-2xl sm:h-96", className)}
    />
  );
}

/** GPS route of an activity, edge-to-edge in a card. */
export function ActivityMap({ route }: { route: Array<[number, number]> }) {
  return (
    <Card>
      <CardContent className="p-0">
        <RouteMap route={route} />
      </CardContent>
    </Card>
  );
}
