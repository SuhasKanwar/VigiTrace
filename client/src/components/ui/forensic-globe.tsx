"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { BufferGeometry, Float32BufferAttribute, type Group, Line, LineBasicMaterial, LineSegments, type Mesh, QuadraticBezierCurve3, Vector3 } from "three";
import countryOutlines from "@/data/country-outlines.json";

type Palette = Record<"mechanism" | "edge" | "line" | "primary" | "secondary" | "surface" | "muted", string>;

function globePoint(longitude: number, latitude: number, radius: number) {
    const phi = (90 - latitude) * Math.PI / 180;
    const theta = (longitude + 180) * Math.PI / 180;
    return new Vector3(-radius * Math.sin(phi) * Math.cos(theta), radius * Math.cos(phi), radius * Math.sin(phi) * Math.sin(theta));
}

const NODES = [[77.2, 28.6], [-0.1, 51.5], [55.3, 25.2], [103.8, 1.35], [-74, 40.7], [151.2, -33.8]]
    .map(([longitude, latitude]) => globePoint(longitude, latitude, 1.79));
const ROUTES = [[0, 1], [0, 2], [0, 4], [1, 5], [2, 3], [3, 5]].map(([from, to]) => {
    const start = NODES[from];
    const end = NODES[to];
    const control = start.clone().add(end).normalize().multiplyScalar(2.35);
    return new QuadraticBezierCurve3(start, control, end);
});
const COUNTRY_GEOMETRY = new BufferGeometry();
const COUNTRY_SEGMENTS = (countryOutlines as number[][][]).flatMap((ring) => ring.slice(1).flatMap((point, index) => {
    const start = globePoint(ring[index][0], ring[index][1], 1.765);
    const end = globePoint(point[0], point[1], 1.765);
    return [...start.toArray(), ...end.toArray()];
}));
COUNTRY_GEOMETRY.setAttribute("position", new Float32BufferAttribute(COUNTRY_SEGMENTS, 3));
let paletteSnapshot: Palette | null = null;

function CountryBorders({ color }: { color: string }) {
    const material = useMemo(() => new LineBasicMaterial({ color, transparent: true, opacity: 0.72 }), [color]);
    const borders = useMemo(() => new LineSegments(COUNTRY_GEOMETRY, material), [material]);
    useEffect(() => () => material.dispose(), [material]);
    return <primitive object={borders} />;
}

function MovingRoute({ route, color, delay }: { route: QuadraticBezierCurve3; color: string; delay: number }) {
    const markerRef = useRef<Mesh>(null);
    const geometry = useMemo(() => new BufferGeometry(), []);
    const material = useMemo(() => new LineBasicMaterial({ color, transparent: true, opacity: 0.9 }), [color]);
    const line = useMemo(() => new Line(geometry, material), [geometry, material]);

    useEffect(() => () => {
        geometry.dispose();
        material.dispose();
    }, [geometry, material]);

    useFrame(({ clock }) => {
        const progress = (clock.elapsedTime * 0.11 + delay) % 1;
        const start = Math.max(0, progress - 0.24);
        const points = Array.from({ length: 18 }, (_, index) => route.getPoint(start + (progress - start) * index / 17));
        geometry.setFromPoints(points);
        markerRef.current?.position.copy(route.getPoint(progress));
    });

    return <group><primitive object={line} /><mesh ref={markerRef}><sphereGeometry args={[0.045, 12, 12]} /><meshBasicMaterial color={color} /></mesh></group>;
}

function getPalette() {
    if (paletteSnapshot) return paletteSnapshot;
    const styles = getComputedStyle(document.documentElement);
    paletteSnapshot = {
        mechanism: styles.getPropertyValue("--mechanism-color").trim(),
        edge: styles.getPropertyValue("--mechanism-edge").trim(),
        line: styles.getPropertyValue("--mechanism-line").trim(),
        primary: styles.getPropertyValue("--primary-color").trim(),
        secondary: styles.getPropertyValue("--secondary-color").trim(),
        surface: styles.getPropertyValue("--surface-color").trim(),
        muted: styles.getPropertyValue("--surface-muted-color").trim(),
    };
    return paletteSnapshot;
}

function GlobeScene({ palette }: { palette: Palette }) {
    const globeRef = useRef<Group>(null);
    const reduceMotion = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    useFrame((state, delta) => {
        if (!globeRef.current || reduceMotion) return;
        globeRef.current.rotation.y += delta * 0.12;
        globeRef.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.35) * 0.08;
    });

    return (
        <group ref={globeRef}>
            <mesh>
                <sphereGeometry args={[1.75, 64, 64]} />
                <meshStandardMaterial color={palette.surface} emissive={palette.primary} emissiveIntensity={0.025} metalness={0.08} roughness={0.82} />
            </mesh>
            <CountryBorders color={palette.line} />
            {ROUTES.map((route, index) => <MovingRoute color={index % 2 ? palette.secondary : palette.primary} delay={index / ROUTES.length} key={index} route={route} />)}
            {NODES.map((position, index) => <group key={index} position={position}><mesh><sphereGeometry args={[0.065, 16, 16]} /><meshBasicMaterial color={palette.primary} /></mesh><mesh><sphereGeometry args={[0.11, 16, 16]} /><meshBasicMaterial color={palette.secondary} opacity={0.22} transparent /></mesh></group>)}
        </group>
    );
}

export default function ForensicGlobe() {
    const palette = useSyncExternalStore(() => () => undefined, getPalette, () => null as Palette | null);

    if (!palette) return <div aria-hidden="true" className="h-full w-full animate-loading-pulse bg-(--surface-muted-color)" />;

    return <Canvas aria-label="Animated global evidence network" camera={{ fov: 40, position: [0, 0, 5.6] }} dpr={[1, 1.5]} role="img"><ambientLight color={palette.muted} intensity={2.4} /><pointLight color={palette.primary} intensity={12} position={[3, 2, 4]} /><pointLight color={palette.secondary} intensity={8} position={[-3, -2, 2]} /><GlobeScene palette={palette} /></Canvas>;
}
