"""Selección de consolas para X55/RK3566; soporte no equivale a FPS garantizados."""

REFERENCE = 'https://github.com/ROCKNIX/distribution/blob/next/documentation/PER_DEVICE_DOCUMENTATION/RK3566/SUPPORTED_EMULATORS_AND_CORES.md'

# slug del sitio, nombre, carpeta comprobada en ROCKNIX, extensiones de ROM sin comprimir.
_SYSTEMS = [
    ('gameboy', 'Game Boy', 'gb', '.gb .gbc'),
    ('gameboy-color', 'Game Boy Color', 'gbc', '.gb .gbc'),
    ('gameboy-advance', 'Game Boy Advance', 'gba', '.gba'),
    ('nintendo', 'NES', 'nes', '.nes .unf .unif'),
    ('super-nintendo', 'Super Nintendo', 'snes', '.sfc .smc .fig .swc'),
    ('sega-genesis', 'Mega Drive', 'megadrive', '.md .gen .bin .smd .sg'),
    ('sega-master-system', 'Master System', 'mastersystem', '.sms .bin'),
    ('game-gear', 'Game Gear', 'gamegear', '.gg .bin'),
    ('sega-sg1000', 'SG-1000', 'sg-1000', '.sg .bin'),
    ('sega-32x', 'Sega 32X', 'sega32x', '.32x .bin .md .smd'),
    ('turbografx-16', 'TurboGrafx-16', 'tg16', '.pce .bin'),
    ('super-grafx', 'SuperGrafx', 'sgfx', '.pce .sgx'),
    ('nintendo-famicom-disk-system', 'Famicom Disk System', 'fds', '.fds'),
    ('atari-2600', 'Atari 2600', 'atari2600', '.a26 .bin'),
    ('atari-5200-supersystem', 'Atari 5200', 'atari5200', '.a52 .rom .bin .car .xex .atr .xfd .atx .cdm .cas'),
    ('atari-7800-prosystem', 'Atari 7800', 'atari7800', '.a78 .bin'),
    ('atari-lynx', 'Atari Lynx', 'atarilynx', '.lnx .lyx .o'),
    ('colecovision', 'ColecoVision', 'coleco', '.col .rom .bin'),
    ('intellivision', 'Intellivision', 'intellivision', '.int .rom .bin'),
    ('gce-vectrex', 'Vectrex', 'vectrex', '.vec .gam .bin'),
    ('magnavox-odyssey-2', 'Odyssey 2', 'odyssey', '.bin'),
    ('philips-videopac', 'Videopac', 'videopac', '.bin'),
    ('fairchild-channel-f', 'Channel F', 'channelf', '.chf .bin'),
    ('wonderswan', 'WonderSwan', 'wonderswan', '.ws .wsc'),
    ('nintendo-virtual-boy', 'Virtual Boy', 'virtualboy', '.vb'),
    ('nintendo-pokemon-mini', 'Pokemon Mini', 'pokemini', '.min'),
    ('neo-geo-pocket', 'Neo Geo Pocket', 'ngp', '.ngp .ngc'),
    ('neo-geo-pocket-color', 'Neo Geo Pocket Color', 'ngpc', '.ngp .ngc'),
    ('watara-supervision', 'Supervision', 'supervision', '.sv'),
    ('sufami-turbo', 'Sufami Turbo', 'sufami', '.st'),
    ('epoch-super-cassette-vision', 'Super Cassette Vision', 'scv', '.cart .bin .rom .0'),
    ('snk-neo-geo', 'Neo Geo', 'neogeo', '.neo'),
    ('playstation', 'PlayStation', 'psx', '.iso .chd .pbp .bin .cue .img .m3u'),
    ('playstation-portable', 'PSP', 'psp', '.iso .cso .pbp .chd'),
    ('nintendo-64', 'Nintendo 64', 'n64', '.z64 .n64 .v64'),
    ('nintendo-ds', 'Nintendo DS', 'nds', '.nds'),
    ('dreamcast', 'Dreamcast', 'dreamcast', '.cdi .gdi .chd .m3u .cue'),
    ('sega-saturn', 'Saturn', 'saturn', '.iso .chd .cue'),
]
VARIABLE = {'playstation-portable', 'nintendo-64', 'nintendo-ds', 'dreamcast', 'sega-saturn'}
DISC = {'playstation', 'playstation-portable', 'dreamcast', 'sega-saturn'}
SYSTEMS = {}
for slug, name, folder, extensions in _SYSTEMS:
    SYSTEMS[slug] = {'name': name, 'folder': folder, 'extensions': extensions.split(),
                     'performance': 'variable' if slug in VARIABLE else 'standard',
                     'archive_mode': 'keep' if folder == 'neogeo' else 'extract'}
    if slug in VARIABLE:
        SYSTEMS[slug]['notice'] = 'Rendimiento variable: depende del juego y de la configuración del emulador.'
    if slug == 'snk-neo-geo':
        SYSTEMS[slug]['notice'] = 'Necesita un romset compatible con el emulador y su BIOS. El comprimido se conserva como ROM.'

SELECTED = tuple(SYSTEMS)
FORMATS = {entry['folder']: set(entry['extensions']) for entry in SYSTEMS.values()}
FORMATS['neogeo'].update(('.zip', '.7z'))
KEEP_ARCHIVES = {'neogeo'}
CARTRIDGE_EXTENSIONS = set().union(*(set(SYSTEMS[slug]['extensions']) for slug in SELECTED
                                  if slug not in DISC and slug != 'snk-neo-geo'))
