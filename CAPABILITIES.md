# Current capability coverage

| Feature | Hardware | Simulation |
| --- | --- | --- |
| Angle, Min / Max / Center, jog, hold/release | Available | Available |
| Named positions: add, edit, remove, recall | Available; stored on Mac | Available; separate storage |
| Motion sequences, cycles, dwell, cancel | Available | Available |
| Travel/center configuration | Read/write with verification | Available |
| Speed, deadband, motor output, acceleration, overload | Read/write with verification on inspected firmware | Simplified model |
| Save settings | Explicit whole-device flash-save command; persistence check pending | Local virtual nonvolatile storage |
| Restore | Connection baseline | Last saved virtual settings |
| Profiles | Matching mode and product/version | Matching simulation mode |
| Direction, fail-safe and connection identity programming | Not exposed | Simplified behavior / metadata |
| Fault injection, virtual reboot, demo reset | Unavailable | Available |
| Position graph, voltage, status flags, activity | Available | Available |
| Motor temperature, output and speed telemetry | Not exposed | Illustrative values |
| Firmware flashing, multiple actuators, multi-turn / continuous rotation | Not implemented | Not implemented |

Hardware configuration is restricted to the observed product register 7961 and version register 21062. Form values come from the device. Apply verifies each register and attempts rollback if a write fails. There is no implicit flash save. Direction and fail-safe are not assigned guessed mappings.

The simulator is a kinematic demonstration, not an electrical, mechanical, thermal or CAN-bus model. Its defaults do not describe the actual servo. Hitec AIO has broader capabilities than this implementation.

Sources: [Hitec CAN/DroneCAN protocol manual](https://www.hiteccs.com/public/uploads/ckeditor/64f8ce92514e01694027410.pdf), [DPC-20 instructions](https://www.hiteccs.com/public/uploads/ckeditor/687542709780f1752515184.pdf), [Hitec feature overview](https://www.hiteccs.com/actuators/product-details/DPC-CAN).
