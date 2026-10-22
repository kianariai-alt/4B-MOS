# Generic bone templates

The femur and tibia meshes are from the OpenSim Gait2392 model by Delp S.L.,
Loan J.P., Hoy M.G., Zajac F.E., Topp E.L., Rosen J.M., Thelen D.G., Anderson F.C.
and Seth A. They are shared under **Creative Commons Attribution 3.0**:
https://creativecommons.org/licenses/by/3.0/

Source repository: https://github.com/opensim-org/opensim-models

Pinned source revision: `d9b05d470b1a481c222372c85b75772faf8f7792`.
The license and credits are explicitly stated in the `<credits>` element of
[gait2392_thelen2003muscle.osim](https://github.com/opensim-org/opensim-models/blob/d9b05d470b1a481c222372c85b75772faf8f7792/Models/Gait2392_Simbody/gait2392_thelen2003muscle.osim).
That model references `femur_r.vtp` and `tibia_r.vtp` in its attached geometry.

| Original path | Original Git blob SHA-1 | Bundled Whitespace-normalized SHA-256 |
|---|---|---|
| Geometry/femur_r.vtp | 8178515e6fee343d61ded7257dc936ec21075b95 | 7afa9aca4c4640f25b5c7ff78eee60c193ca035b0c026a54bf693eb698a41aff |
| Geometry/tibia_r.vtp | d46e7e5d20908fdd3ded7d458825f949690a23b5 | 079a4758e876a49f4969e354c5a9924cddbddf7bc641744fce9b5be7c9254171 |

The bundled XML files have line endings normalized to LF and trailing whitespace removed. The phantom generator
mirrors the right bone shapes for a left-knee illustration, converts metres to
millimetres, translates the two bones to an illustrative joint clearance, crops
and caps the shafts, then voxelizes them. This is **not** the original OpenSim
kinematic model or an anatomically validated pose. Patella, fibula, cartilage,
menisci, ligaments and tendons are newly constructed procedural illustrations,
not OpenSim meshes or inferred patient segmentations.

Soft-tissue shape and attachment conventions were informed by
[OpenStax Anatomy and Physiology 2e, 9.6](https://openstax.org/books/anatomy-and-physiology-2e/pages/9-6-anatomy-of-selected-synovial-joints).
No image or prose from that reference is bundled. The illustration is incomplete
and has not been reviewed by an anatomist; it must not be used for measurements
of a patient, diagnosis, surgical planning or claims of arthroscopy equivalence.
