#!/usr/bin/env python3
import numpy as np
from vispy import scene
from vispy.scene.visuals import InstancedMesh

class CappedCylinderCollection(scene.Node):
    """
    A collection of capped cylinders rendered via two InstancedMesh:
      - one for the side-walls (two rings at z=±0.5)
      - one for both end-caps (bottom & top disks)
    
    All per-instance data is passed in up front.
    """
    _side_vertices = None
    _side_indices  = None
    _disk_vertices = None
    _disk_indices  = None

    def __init__(self,
                 positions:    np.ndarray,   # (N,3)
                 radii:        np.ndarray,   # (N,)
                 heights:      np.ndarray,   # (N,)
                 orientations: np.ndarray,   # (N,3,3)
                 colors:       np.ndarray,   # (N,4)
                 cylinder_segments: int = 32,
                 disk_slices:       int = 32,
                 parent=None):
        super().__init__(parent=parent)
        self.N = len(positions)
        assert positions.shape    == (self.N, 3)
        assert radii.shape        == (self.N,)
        assert heights.shape      == (self.N,)
        assert orientations.shape == (self.N, 3, 3)
        assert colors.shape       == (self.N, 4)

        self.positions    = positions.astype(np.float32)
        self.radii        = radii.astype(np.float32)
        self.heights      = heights.astype(np.float32)
        self.orientations = orientations.astype(np.float32)
        self.colors       = colors.astype(np.float32)

        self._segs   = cylinder_segments
        self._slices = disk_slices

        # ─── 1) build shared side-wall geometry (two rings at z=±0.5) ───
        if CappedCylinderCollection._side_vertices is None:
            angles    = np.linspace(0.0, 2.0*np.pi, self._segs,
                                     endpoint=False, dtype=np.float32)
            circle_pts = np.stack([np.cos(angles), np.sin(angles)], axis=1)
            bottom     = np.column_stack([circle_pts,
                                          -0.5 * np.ones(self._segs, dtype=np.float32)])
            top        = np.column_stack([circle_pts,
                                          +0.5 * np.ones(self._segs, dtype=np.float32)])
            verts = np.vstack([bottom, top]).astype(np.float32)

            idx = []
            for i in range(self._segs):
                ni = (i + 1) % self._segs
                idx.append([i,           i + self._segs,   ni])
                idx.append([ni,          i + self._segs,   ni + self._segs])
            inds = np.array(idx, dtype=np.uint32)

            CappedCylinderCollection._side_vertices = verts
            CappedCylinderCollection._side_indices  = inds

        side_verts = CappedCylinderCollection._side_vertices
        side_faces = CappedCylinderCollection._side_indices

        # ─── 2) compute per-instance side transforms ───────────────────
        side_transforms = np.zeros((self.N, 3, 3), dtype=np.float32)
        for k in range(self.N):
            S = np.diag([self.radii[k], self.radii[k], self.heights[k]]).astype(np.float32)
            side_transforms[k] = self.orientations[k] @ S

        # ─── 3) create side-wall InstancedMesh ─────────────────────────
        self._side_mesh = InstancedMesh(
            vertices=side_verts,
            faces=side_faces,
            instance_positions=self.positions,
            instance_transforms=side_transforms,
            instance_colors=self.colors,
            parent=self
        )

        # ─── 4) build shared disk geometry for caps ────────────────────
        if CappedCylinderCollection._disk_vertices is None:
            angles = np.linspace(0.0, 2.0*np.pi, self._slices,
                                 endpoint=False, dtype=np.float32)
            circle_pts = np.stack([np.cos(angles), np.sin(angles)], axis=1)
            verts2d = np.vstack([[0.0, 0.0], circle_pts]).astype(np.float32)
            verts3d = np.zeros((verts2d.shape[0], 3), dtype=np.float32)
            verts3d[:, :2] = verts2d
            idx = [[0, i, i+1] for i in range(1, self._slices)]
            idx.append([0, self._slices, 1])
            CappedCylinderCollection._disk_vertices = verts3d
            CappedCylinderCollection._disk_indices  = np.array(idx, dtype=np.uint32)

        disk_verts = CappedCylinderCollection._disk_vertices
        disk_faces = CappedCylinderCollection._disk_indices

        # ─── 5) compute per-instance cap positions & transforms ────────
        # local Z axis for each instance
        axes    = self.orientations[:, :, 2]            # (N,3)
        half_h  = (self.heights * 0.5)[:, None]         # (N,1)

        pos0 = self.positions - axes * half_h
        pos1 = self.positions + axes * half_h

        cap_transforms = np.zeros((self.N, 3, 3), dtype=np.float32)
        for k in range(self.N):
            S2 = np.diag([self.radii[k], self.radii[k], 1.0]).astype(np.float32)
            cap_transforms[k] = self.orientations[k] @ S2

        cap_positions  = np.vstack([pos0, pos1])        # (2N,3)
        cap_transforms = np.vstack([cap_transforms, cap_transforms])  # (2N,3,3)
        cap_colors     = np.vstack([self.colors, self.colors])        # (2N,4)

        # ─── 6) create cap-disk InstancedMesh ─────────────────────────
        self._cap_mesh = InstancedMesh(
            vertices=disk_verts,
            faces=disk_faces,
            instance_positions=cap_positions,
            instance_transforms=cap_transforms,
            instance_colors=cap_colors,
            parent=self
        )

    def set_colors(self, new_colors: np.ndarray):
        """Update per-segment colors (shape must be (N,4))."""
        assert new_colors.shape == (self.N, 4)
        self.colors = new_colors.astype(np.float32)
        self._side_mesh.instance_colors = self.colors
        self._side_mesh.update()
        cap_cols = np.vstack([self.colors, self.colors])
        self._cap_mesh.instance_colors = cap_cols
        self._cap_mesh.update()

    def set_transforms(self,
                       positions:    np.ndarray = None,
                       radii:        np.ndarray = None,
                       heights:      np.ndarray = None,
                       orientations: np.ndarray = None):
        """
        Update any of positions/radii/heights/orientations (must match N).
        Recomputes instance data for sides and caps.
        """
        if positions is not None:
            assert positions.shape == (self.N, 3)
            self.positions = positions.astype(np.float32)
        if radii is not None:
            assert radii.shape == (self.N,)
            self.radii     = radii.astype(np.float32)
        if heights is not None:
            assert heights.shape == (self.N,)
            self.heights   = heights.astype(np.float32)
        if orientations is not None:
            assert orientations.shape == (self.N, 3, 3)
            self.orientations = orientations.astype(np.float32)

        # recompute and upload side data
        side_t = np.zeros((self.N,3,3), dtype=np.float32)
        for k in range(self.N):
            S = np.diag([self.radii[k], self.radii[k], self.heights[k]]).astype(np.float32)
            side_t[k] = self.orientations[k] @ S
        self._side_mesh.instance_positions   = self.positions
        self._side_mesh.instance_transforms  = side_t
        self._side_mesh.update()

        # recompute and upload caps
        axes   = self.orientations[:,:,2]
        half_h = (self.heights * 0.5)[:,None]
        p0 = self.positions - axes * half_h
        p1 = self.positions + axes * half_h
        cap_t = np.zeros((self.N,3,3), dtype=np.float32)
        for k in range(self.N):
            S2 = np.diag([self.radii[k], self.radii[k], 1.0]).astype(np.float32)
            cap_t[k] = self.orientations[k] @ S2
        cap_pos = np.vstack([p0, p1])
        cap_trans = np.vstack([cap_t, cap_t])
        self._cap_mesh.instance_positions   = cap_pos
        self._cap_mesh.instance_transforms  = cap_trans
        self._cap_mesh.update()
