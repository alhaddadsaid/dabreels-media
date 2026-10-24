# dabreels-media

Episode videos streamed by the DabReels Show app. Every file is cut from a film that may legally be used commercially: Creative Commons BY films by the Blender Foundation, or public-domain silent films.

The files are in the **v1 release** (`<series id>__ep_NN.mp4`, plus `manifest.json` with the cut times). `.github/workflows/media.yml` rebuilds them with `tools/media/build.py` from the sources listed in `tools/media/films.json`.

## Changes made to every film

Each film was cut into short episodes and reframed for vertical phones (the picture is centred on a blurred copy of itself). Piano music was added to the silent films. Nothing else was changed.

## Credits and licences

| Series | Film | Credit | Licence |
|---|---|---|---|
| tears_of_steel | Tears of Steel (2012) | (CC) Blender Foundation \| mango.blender.org | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| sintel | Sintel (2010) | © copyright Blender Foundation \| durian.blender.org | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| big_buck_bunny | Big Buck Bunny (2008) | (c) copyright 2008, Blender Foundation / www.bigbuckbunny.org | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| spring | Spring (2019) | © Blender Foundation \| cloud.blender.org/spring | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| coffee_run | Coffee Run (2020) | (CC) Blender Foundation \| studio.blender.org | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| wing_it | Wing It! (2023) | (CC) Blender Foundation \| studio.blender.org | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| caminandes | Caminandes 1: Llama Drama, 2: Gran Dillama, 3: Llamigos (2013-2016) | (CC) Blender Foundation \| caminandes.com | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| the_general | The General (1926), Buster Keaton and Clyde Bruckman | Copy from [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:The_General_1926_720p.webm) | Public domain |
| safety_last | Safety Last! (1923), Harold Lloyd, dir. Fred C. Newmeyer and Sam Taylor | Copy from [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Safety_Last_(1923).webm) | Public domain |

Music on the silent films: ragtime by Scott Joplin and others, public-domain piano recordings by Gnissah on Wikimedia Commons (track list in `tools/media/films.json`).

Logos and trademarks of the Blender Foundation are not covered by the Creative Commons licences and are not used to promote the app.
