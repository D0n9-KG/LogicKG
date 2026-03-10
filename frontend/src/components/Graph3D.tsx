import { useEffect, useMemo, useRef } from 'react'
import ForceGraph3D from '3d-force-graph'
import * as THREE from 'three'
import { useI18n } from '../i18n'
import { buildFitAllCameraTarget, buildGraph3DSceneConfig, buildGraph3DViewConfig } from './graph3dModel'
import type { GraphElement, SelectedNode } from '../state/types'

type Props = {
  elements: GraphElement[]
  onSelectNode: (node: SelectedNode | null) => void
  transitioning: boolean
}

type FGNode = {
  id: string
  label: string
  kind: string
  clusterKey?: string
  qualityTier?: string
  ingested?: boolean
  paperId?: string
  textbookId?: string
  val: number
  color: string
  x?: number
  y?: number
  z?: number
}

type FGLink = {
  source: string
  target: string
  kind: string
  weight: number
}

type Graph3DHandle = {
  graphData: (data?: { nodes: FGNode[]; links: FGLink[] }) => { nodes: FGNode[]; links: FGLink[] } | void
  zoomToFit: (ms?: number, paddingPx?: number, nodeFilterFn?: (node: FGNode) => boolean) => void
  cameraPosition: (position?: { x?: number; y?: number; z?: number }, lookAt?: { x: number; y: number; z: number }, ms?: number) => void
  getGraphBbox: (nodeFilterFn?: (node: FGNode) => boolean) => { x: [number, number]; y: [number, number]; z: [number, number] } | null
  onEngineStop: (callback: (() => void) | null) => void
  controls: () =>
    | {
        enableDamping?: boolean
        dampingFactor?: number
        rotateSpeed?: number
        zoomSpeed?: number
        panSpeed?: number
        minDistance?: number
        maxDistance?: number
        autoRotate?: boolean
        autoRotateSpeed?: number
      }
    | null
  camera: () => THREE.Camera & { position: THREE.Vector3 }
  scene: () => THREE.Scene
  d3VelocityDecay: (value: number) => void
  d3Force: (name: string) => unknown
}

const LABEL_SHOW_DISTANCE = 190

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function nodeColor(kind: string, tier?: string, ingested?: boolean): string {
  if (kind === 'paper') {
    if (ingested === false) return '#4f6d89'
    if (tier === 'A1') return '#7dd3fc'
    if (tier === 'A2') return '#38bdf8'
    if (tier === 'B1') return '#0ea5e9'
    if (tier === 'B2') return '#0284c7'
    if (tier === 'C') return '#0369a1'
    return '#0ea5e9'
  }
  if (kind === 'textbook') return '#f59e0b'
  if (kind === 'chapter') return '#22c55e'
  if (kind === 'community') return '#fb7185'
  if (kind === 'logic') return '#34d399'
  if (kind === 'claim') return '#fb923c'
  if (kind === 'prop' || kind === 'proposition') return '#facc15'
  if (kind === 'group') return '#2dd4bf'
  if (kind === 'entity') return '#14b8a6'
  return '#94a3b8'
}

function nodeSize(kind: string, degree?: number, ingested?: boolean): number {
  const d = clamp(Number(degree ?? 0), 0, 20)
  if (kind === 'textbook') return 10.5 + d * 0.32
  if (kind === 'chapter') return 7.2 + d * 0.24
  if (kind === 'community') return 6.4 + d * 0.24
  if (kind === 'paper') return ingested === false ? 3.8 + d * 0.2 : 5.8 + d * 0.34
  if (kind === 'group') return 6.2 + d * 0.28
  if (kind === 'prop' || kind === 'proposition') return 5.6 + d * 0.24
  if (kind === 'logic' || kind === 'claim') return 4.8 + d * 0.24
  if (kind === 'citation') return 3.2 + d * 0.14
  return 4 + d * 0.2
}

function linkColor(kind: string): string {
  if (kind === 'contains') return 'rgba(251, 191, 36, 0.42)'
  if (kind === 'cites') return 'rgba(125, 211, 252, 0.5)'
  if (kind === 'supports') return 'rgba(74, 222, 128, 0.55)'
  if (kind === 'challenges') return 'rgba(248, 113, 113, 0.6)'
  if (kind === 'supersedes') return 'rgba(250, 204, 21, 0.56)'
  if (kind === 'similar') return 'rgba(148, 163, 184, 0.45)'
  if (kind === 'maps_to') return 'rgba(20, 184, 166, 0.56)'
  return 'rgba(148, 163, 184, 0.42)'
}

function particleColor(kind: string): string {
  if (kind === 'contains') return '#fde68a'
  if (kind === 'supports') return '#86efac'
  if (kind === 'challenges') return '#fca5a5'
  if (kind === 'supersedes') return '#fde047'
  return '#bae6fd'
}

function drawRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.lineTo(x + width - radius, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius)
  ctx.lineTo(x + width, y + height - radius)
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height)
  ctx.lineTo(x + radius, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius)
  ctx.lineTo(x, y + radius)
  ctx.quadraticCurveTo(x, y, x + radius, y)
  ctx.closePath()
}

function createLabelSprite(text: string, nodeRadius: number): THREE.Sprite {
  const compact = text.length > 34 ? `${text.slice(0, 33)}...` : text
  const logicalWidth = clamp(128 + compact.length * 6, 160, 320)
  const logicalHeight = 52
  const canvas = document.createElement('canvas')
  canvas.width = logicalWidth * 2
  canvas.height = logicalHeight * 2
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    const fallback = new THREE.Sprite(new THREE.SpriteMaterial({ color: 0xffffff }))
    fallback.visible = false
    return fallback
  }
  ctx.scale(2, 2)
  ctx.clearRect(0, 0, logicalWidth, logicalHeight)

  drawRoundedRect(ctx, 1.5, 6, logicalWidth - 3, logicalHeight - 12, 10)
  ctx.fillStyle = 'rgba(4, 12, 27, 0.86)'
  ctx.fill()
  ctx.strokeStyle = 'rgba(186, 230, 253, 0.42)'
  ctx.lineWidth = 1
  ctx.stroke()

  ctx.font = '600 15px "Fira Sans", "IBM Plex Sans", sans-serif'
  ctx.fillStyle = 'rgba(240, 250, 255, 0.96)'
  ctx.textBaseline = 'middle'
  ctx.fillText(compact, 12, logicalHeight / 2 + 0.5)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.needsUpdate = true

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  })

  const sprite = new THREE.Sprite(material)
  sprite.scale.set(logicalWidth / 10.8, logicalHeight / 9.5, 1)
  sprite.position.set(0, nodeRadius + 7, 0)
  sprite.visible = false
  return sprite
}

function disposeSprite(sprite: THREE.Sprite) {
  const mat = sprite.material as THREE.SpriteMaterial
  mat.map?.dispose()
  mat.dispose()
}

function applyNavHint(container: HTMLDivElement | null, hint: string) {
  if (!container) return
  const navInfo = container.querySelector<HTMLDivElement>('.scene-nav-info')
  if (!navInfo) return
  navInfo.textContent = hint
}

function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

function seededLocalOffset(kind: string, index: number, total: number, seed: number) {
  const angle = ((index + (seed % 17) / 17) / Math.max(total, 1)) * Math.PI * 2
  const wobble = ((seed % 29) / 29 - 0.5) * 18
  if (kind === 'textbook') return { x: 0, y: 0, z: wobble * 0.5 }
  if (kind === 'chapter') return { x: Math.cos(angle) * 82, y: Math.sin(angle) * 64, z: wobble }
  if (kind === 'community') return { x: Math.cos(angle) * 142, y: Math.sin(angle) * 112, z: wobble * 1.5 }
  if (kind === 'entity') return { x: Math.cos(angle) * 220, y: Math.sin(angle) * 172, z: wobble * 2.1 }
  return { x: Math.cos(angle) * 268, y: Math.sin(angle) * 196, z: wobble * 2.4 }
}

function seedClusteredPositions(nodes: FGNode[]) {
  const hasTextbookStructures = nodes.some((node) => node.kind === 'textbook' || node.kind === 'chapter' || node.kind === 'community')
  if (!hasTextbookStructures) return

  const groups = new Map<string, FGNode[]>()
  const freeNodes: FGNode[] = []
  for (const node of nodes) {
    if (!node.clusterKey) {
      freeNodes.push(node)
      continue
    }
    const bucket = groups.get(node.clusterKey) ?? []
    bucket.push(node)
    groups.set(node.clusterKey, bucket)
  }

  const clusterKeys = Array.from(groups.keys()).sort((a, b) => a.localeCompare(b))
  const clusterOrbit = clusterKeys.length <= 1 ? 0 : Math.max(420, clusterKeys.length * 140)

  clusterKeys.forEach((key, clusterIndex) => {
    const members = groups.get(key) ?? []
    const angle = clusterKeys.length <= 1 ? 0 : (clusterIndex / clusterKeys.length) * Math.PI * 2
    const centerX = clusterKeys.length <= 1 ? -180 : Math.cos(angle) * clusterOrbit
    const centerY = clusterKeys.length <= 1 ? 40 : Math.sin(angle) * clusterOrbit * 0.62
    const centerZ = clusterKeys.length <= 1 ? 0 : Math.sin(angle * 1.7) * 180
    const ordered = [...members].sort((a, b) => {
      const kindRank = (kind: string) => {
        if (kind === 'textbook') return 0
        if (kind === 'chapter') return 1
        if (kind === 'community') return 2
        if (kind === 'entity') return 3
        return 4
      }
      return kindRank(a.kind) - kindRank(b.kind) || a.id.localeCompare(b.id)
    })

    ordered.forEach((node, index) => {
      const local = seededLocalOffset(node.kind, index, ordered.length, hashString(node.id))
      node.x = centerX + local.x
      node.y = centerY + local.y
      node.z = centerZ + local.z
    })
  })

  const paperNodes = freeNodes.filter((node) => node.kind === 'paper' || node.kind === 'citation')
  const outerRadius = Math.max(clusterOrbit + 520, 860)
  paperNodes.forEach((node, index) => {
    const angle = (index / Math.max(1, paperNodes.length)) * Math.PI * 2
    const seed = hashString(node.id)
    node.x = Math.cos(angle) * outerRadius
    node.y = Math.sin(angle) * outerRadius * 0.58
    node.z = ((seed % 41) - 20) * 14
  })
}

export default function Graph3D({ elements, onSelectNode, transitioning }: Props) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph3DHandle | null>(null)
  const frameRef = useRef<number | null>(null)
  const autoFitTimerRef = useRef<number | null>(null)
  const pendingAutoFitRef = useRef(false)
  const viewConfigRef = useRef(buildGraph3DViewConfig(0))
  const labelSpritesRef = useRef<Map<string, THREE.Sprite>>(new Map())
  const hoveredNodeIdRef = useRef<string | null>(null)
  const onSelectNodeRef = useRef(onSelectNode)

  useEffect(() => {
    onSelectNodeRef.current = onSelectNode
  }, [onSelectNode])

  const { nodes, links } = useMemo(() => {
    const degreeMap = new Map<string, number>()
    for (const el of elements) {
      if (el.group !== 'edges') continue
      const source = String((el.data as { source: string }).source ?? '')
      const target = String((el.data as { target: string }).target ?? '')
      degreeMap.set(source, (degreeMap.get(source) ?? 0) + 1)
      degreeMap.set(target, (degreeMap.get(target) ?? 0) + 1)
    }

    const nextNodes: FGNode[] = elements
      .filter((e) => e.group === 'nodes')
      .map((e) => ({
        id: e.data.id,
        label: e.data.label,
        kind: e.data.kind,
        clusterKey: e.data.clusterKey,
        qualityTier: e.data.qualityTier,
        ingested: e.data.ingested,
        paperId: e.data.paperId,
        textbookId: e.data.textbookId,
        val: nodeSize(e.data.kind, degreeMap.get(e.data.id), e.data.ingested),
        color: nodeColor(e.data.kind, e.data.qualityTier, e.data.ingested),
      }))

    const nextLinks: FGLink[] = elements
      .filter((e) => e.group === 'edges')
      .map((e) => ({
        source: (e.data as { source: string }).source,
        target: (e.data as { target: string }).target,
        kind: e.data.kind,
        weight: clamp(Number((e.data as { weight?: number }).weight ?? 0.5), 0.1, 1),
      }))

    seedClusteredPositions(nextNodes)
    return { nodes: nextNodes, links: nextLinks }
  }, [elements])

  const applyGraphFit = (fg: Graph3DHandle, animateMs: number) => {
    const container = containerRef.current
    const graphData = fg.graphData() as { nodes: FGNode[]; links: FGLink[] } | void
    const nodeCount = graphData?.nodes.length ?? nodes.length
    const finiteNodeFilter = (node: FGNode) => Number.isFinite(node.x) && Number.isFinite(node.y) && Number.isFinite(node.z)
    const camera = fg.camera() as THREE.Camera & {
      position: THREE.Vector3
      fov?: number
      aspect?: number
      far?: number
      updateProjectionMatrix?: () => void
    }
    const bounds = fg.getGraphBbox?.(finiteNodeFilter)
    if (!container || !bounds) {
      fg.zoomToFit(animateMs, viewConfigRef.current.autoFitPadding)
      return
    }

    const aspect = Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1)
    const fitTarget = buildFitAllCameraTarget(bounds, {
      aspect,
      fovDeg: camera instanceof THREE.PerspectiveCamera ? camera.fov : Number(camera.fov) || 40,
      minDistance: viewConfigRef.current.minDistance,
    })
    if (![fitTarget.position.x, fitTarget.position.y, fitTarget.position.z, fitTarget.lookAt.x, fitTarget.lookAt.y, fitTarget.lookAt.z].every(Number.isFinite)) {
      fg.zoomToFit(animateMs, viewConfigRef.current.autoFitPadding, finiteNodeFilter)
      return
    }
    viewConfigRef.current = buildGraph3DViewConfig(nodeCount, fitTarget.diagonal)
    const sceneConfig = buildGraph3DSceneConfig(nodeCount, fitTarget.diagonal, fitTarget.distance)

    const controls = fg.controls()
    if (controls) {
      controls.zoomSpeed = viewConfigRef.current.zoomSpeed
      controls.minDistance = viewConfigRef.current.minDistance
      controls.maxDistance = Math.max(viewConfigRef.current.maxDistance, Math.round(fitTarget.distance * 8))
    }

    if (camera instanceof THREE.PerspectiveCamera) {
      camera.aspect = aspect
      camera.far = Math.max(camera.far, fitTarget.distance * 10)
      camera.updateProjectionMatrix()
    } else if (typeof camera.updateProjectionMatrix === 'function' && typeof camera.far === 'number') {
      camera.far = Math.max(camera.far, fitTarget.distance * 10)
        camera.updateProjectionMatrix()
    }

    fg.scene().fog = new THREE.FogExp2(0x01030a, sceneConfig.fogDensity)
    fg.cameraPosition(fitTarget.position, fitTarget.lookAt, animateMs)
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const labelSprites = labelSpritesRef.current
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    viewConfigRef.current = buildGraph3DViewConfig(nodes.length)
    const fg = (() => {
      const originalWarn = console.warn
      const suppressClockWarning = (message: unknown) =>
        typeof message === 'string' && message.includes('THREE.THREE.Clock: This module has been deprecated')
      console.warn = (...args: unknown[]) => {
        if (suppressClockWarning(args[0])) return
        originalWarn(...args)
      }
      try {
        return new ForceGraph3D(container, { controlType: 'orbit' })
      } finally {
        console.warn = originalWarn
      }
    })()

    fg
      .backgroundColor('#01030a')
      .nodeLabel((n) => (n as FGNode).label)
      .nodeColor((n) => (n as FGNode).color)
      .nodeVal((n) => (n as FGNode).val)
      .nodeThreeObject((n) => {
        const node = n as FGNode
        const imported = node.kind === 'paper' ? node.ingested !== false : true
        const radius = Math.max(3.4, node.val)
        const color = new THREE.Color(node.color)
        const group = new THREE.Group()

        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(radius, 18, 18),
          new THREE.MeshStandardMaterial({
            color,
            emissive: color.clone().multiplyScalar(0.28),
            emissiveIntensity: 1.08,
            roughness: 0.32,
            metalness: 0.12,
            transparent: true,
            opacity: imported ? 0.96 : 0.56,
          }),
        )
        group.add(sphere)

        const aura = new THREE.Mesh(
          new THREE.SphereGeometry(radius * 1.8, 16, 16),
          new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity: imported ? 0.08 : 0.03,
            side: THREE.BackSide,
          }),
        )
        group.add(aura)

        const ring = new THREE.Mesh(
          new THREE.TorusGeometry(radius * 1.24, Math.max(0.24, radius * 0.08), 10, 40),
          new THREE.MeshBasicMaterial({
            color: color.clone().lerp(new THREE.Color('#f8fafc'), 0.4),
            transparent: true,
            opacity: imported ? 0.42 : 0.22,
          }),
        )
        ring.rotation.x = Math.PI / 2.3
        group.add(ring)

        const labelSprite = createLabelSprite(node.label, radius)
        labelSprites.set(node.id, labelSprite)
        group.add(labelSprite)

        return group
      })
      .nodeThreeObjectExtend(false)
      .linkWidth((link) => 0.8 + (link as FGLink).weight * 1.5)
      .linkColor((link) => linkColor((link as FGLink).kind))
      .linkOpacity(0.82)
      .linkDirectionalParticles((link) => ((link as FGLink).kind === 'supports' || (link as FGLink).kind === 'challenges' ? 2 : 1))
      .linkDirectionalParticleWidth((link) => ((link as FGLink).kind === 'supports' ? 2.6 : 2))
      .linkDirectionalParticleColor((link) => particleColor((link as FGLink).kind))
      .onNodeClick((n) => {
        const node = n as FGNode
        onSelectNodeRef.current({
          id: node.id,
          kind: node.kind,
          label: node.label,
          paperId: node.paperId,
          textbookId: node.textbookId,
        })
      })
      .onNodeHover((n) => {
        hoveredNodeIdRef.current = n ? (n as FGNode).id : null
        container.style.cursor = n ? 'pointer' : 'default'
      })
      .onBackgroundClick(() => onSelectNodeRef.current(null))

    const controls = fg.controls() as
      | {
          enableDamping?: boolean
          dampingFactor?: number
          rotateSpeed?: number
          zoomSpeed?: number
          panSpeed?: number
          minDistance?: number
          maxDistance?: number
          autoRotate?: boolean
          autoRotateSpeed?: number
        }
      | null
    if (controls) {
      controls.enableDamping = true
      controls.dampingFactor = 0.08
      controls.rotateSpeed = 0.7
      controls.zoomSpeed = viewConfigRef.current.zoomSpeed
      controls.panSpeed = 0.8
      controls.minDistance = viewConfigRef.current.minDistance
      controls.maxDistance = viewConfigRef.current.maxDistance
      controls.autoRotate = false
      controls.autoRotateSpeed = prefersReducedMotion ? 0 : 0.2
    }

    fg.d3VelocityDecay(0.32)
    const chargeForce = fg.d3Force('charge') as { strength?: (value: number) => void } | undefined
    chargeForce?.strength?.(-120)
    const linkForce = fg.d3Force('link') as { distance?: (fn: (l: FGLink) => number) => void; strength?: (v: number) => void } | undefined
    linkForce?.distance?.((l) => {
      if (l.kind === 'contains') return 58 + (1 - l.weight) * 28
      if (l.kind === 'relates_to') return 82 + (1 - l.weight) * 32
      if (l.kind === 'maps_to') return 108 + (1 - l.weight) * 36
      if (l.kind === 'cites') return 150 + (1 - l.weight) * 60
      return 95 + (1 - l.weight) * 50
    })
    linkForce?.strength?.(0.22)

    const scene = fg.scene()
    scene.fog = null
    scene.add(new THREE.AmbientLight(0x94a3b8, 1.5))
    scene.add(new THREE.HemisphereLight(0x7dd3fc, 0x020617, 1.3))
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.55)
    keyLight.position.set(90, 120, 120)
    scene.add(keyLight)
    const rimLight = new THREE.PointLight(0x7dd3fc, 1.25, 420)
    rimLight.position.set(-120, -70, -130)
    scene.add(rimLight)

    const starGeometry = new THREE.BufferGeometry()
    const starPoints = new Float32Array(1200 * 3)
    for (let i = 0; i < 1200; i += 1) {
      starPoints[i * 3] = (Math.random() - 0.5) * 1800
      starPoints[i * 3 + 1] = (Math.random() - 0.5) * 1800
      starPoints[i * 3 + 2] = (Math.random() - 0.5) * 1800
    }
    starGeometry.setAttribute('position', new THREE.BufferAttribute(starPoints, 3))
    const starMaterial = new THREE.PointsMaterial({
      color: 0x9cc7ff,
      size: 1.3,
      transparent: true,
      opacity: 0.26,
      depthWrite: false,
    })
    const stars = new THREE.Points(starGeometry, starMaterial)
    scene.add(stars)

    const scratch = new THREE.Vector3()
    const updateLabels = () => {
      const camera = fg.camera()
      const cameraPosition = camera.position
      const graphData = fg.graphData() as unknown as { nodes: FGNode[] }
      const hoveredId = hoveredNodeIdRef.current

      for (const node of graphData.nodes) {
        const sprite = labelSprites.get(node.id)
        if (!sprite) continue
        const dist = cameraPosition.distanceTo(scratch.set(node.x ?? 0, node.y ?? 0, node.z ?? 0))
        sprite.visible = dist < LABEL_SHOW_DISTANCE || hoveredId === node.id
      }
      frameRef.current = window.requestAnimationFrame(updateLabels)
    }

    fg.onEngineStop(() => {
      if (!pendingAutoFitRef.current || !graphRef.current) return
      applyGraphFit(graphRef.current, viewConfigRef.current.autoFitMs)
      pendingAutoFitRef.current = false
    })

    frameRef.current = window.requestAnimationFrame(updateLabels)
    graphRef.current = fg as unknown as Graph3DHandle
    applyNavHint(container, t('左键旋转，滚轮/中键缩放，右键平移', 'Left-click: rotate, mouse wheel/middle-click: zoom, right-click: pan'))

    return () => {
      if (frameRef.current) window.cancelAnimationFrame(frameRef.current)
      frameRef.current = null
      if (autoFitTimerRef.current) window.clearTimeout(autoFitTimerRef.current)
      autoFitTimerRef.current = null
      pendingAutoFitRef.current = false
      hoveredNodeIdRef.current = null
      container.style.cursor = 'default'

      starGeometry.dispose()
      starMaterial.dispose()
      scene.remove(stars)

      for (const sprite of labelSprites.values()) {
        disposeSprite(sprite)
      }
      labelSprites.clear()

      try {
        ;(fg as { _destructor?: () => void })._destructor?.()
      } catch {
        // no-op
      }
      graphRef.current = null
    }
  }, [t])

  useEffect(() => {
    applyNavHint(
      containerRef.current,
      t('左键旋转，滚轮/中键缩放，右键平移', 'Left-click: rotate, mouse wheel/middle-click: zoom, right-click: pan'),
    )
  }, [t])

  useEffect(() => {
    const fg = graphRef.current
    if (!fg) return
    viewConfigRef.current = buildGraph3DViewConfig(nodes.length)
    const controls = fg.controls()
    if (controls) {
      controls.zoomSpeed = viewConfigRef.current.zoomSpeed
      controls.minDistance = viewConfigRef.current.minDistance
      controls.maxDistance = viewConfigRef.current.maxDistance
    }
    pendingAutoFitRef.current = nodes.length > 0
    fg.graphData({ nodes, links })
    if (autoFitTimerRef.current) window.clearTimeout(autoFitTimerRef.current)
    if (pendingAutoFitRef.current) {
      autoFitTimerRef.current = window.setTimeout(() => {
        autoFitTimerRef.current = null
        if (!graphRef.current) return
        applyGraphFit(graphRef.current, viewConfigRef.current.autoFitMs)
      }, 720)
    }
  }, [links, nodes])

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        opacity: transitioning ? 0.5 : 1,
        transition: 'opacity 220ms ease',
      }}
    />
  )
}
