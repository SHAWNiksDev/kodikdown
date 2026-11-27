# Проверка сайтов в KodikDown 4.7.1

Проверено 27 ноября 2026 года. На ПК использовались Linux x86_64 и KodikDown CLI, на телефоне — Google Pixel 8. Для завершённых загрузок на ПК проверены длительность файла, видео- и аудиодорожки. Результаты относятся к указанным страницам и плеерам. Доступность серий и потоков зависит от сайта.

| Сайт | Что проверено |
| --- | --- |
| [YummyAnime, новый сайт](https://ru.yummyani.me/catalog/item/saga-o-vinlande) | Найдены серии и озвучки Kodik и CVH. Первая серия скачана через Kodik в режиме HLS. Прямая MP4-ссылка отвечала ошибкой 500 или долго не отвечала. |
| [YummyAnime, старый сайт](https://old.yummyani.me/catalog/item/saga-o-vinlande) | Первая серия скачана через CVH в 480p. Файл MP4 содержит видео H.264 и звук AAC. |
| [AnimeGO](https://animego.me/anime/klub-igr-po-vyzhivaniyu-4516) | Первая серия скачана через Kodik. Когда прямой MP4 не открылся, загрузка завершилась через HLS. |
| [AnimeGO, AniBoom](https://animego.me/anime/grotesk-4518) | Страница вернула список плееров, AniBoom отдал HLS. Полная загрузка не завершилась за время проверки. |
| [AnimeGO, карточка без серий](https://animego.me/anime/raz-uzh-my-risuyem-4520) | Страница открылась. Плееры и эпизоды для загрузки не найдены. |
| [AniLiberty](https://aniliberty.top/anime/releases/release/tensei-shitara-ken-deshita-2nd-season) | В Linux и на Pixel 8 найдено девять серий. Проверен действующий адрес и старый формат `/release/<название>.html`. После исправления запроса к CDN первая серия полностью скачалась в 480p на Linux. |
| [AniDUB.life](https://anidub.life/12511-s-devjati-do-shesti.html) | Найдены две серии и потоки 480p и 720p. Сервер сегментов переставал отвечать во время загрузки. |

Отдельно проверены ссылки с открытых в Chrome сайтов [AniDUB.org](https://anidub.org/8175-ty_umeesh_khranit_sekrety.html), [AnimeLib](https://animelib.org/ru/anime/26532--tetsuryou-meet-with-tetsudou-musume-anime) и [YummyAnime.tv](https://yummyanime.tv/series-y73/), а также примеры с [AnimeVost](https://animevost.org/tip/tv/3640-chitose-kun-wa-ramune-bin-no-naka.html), [Jut.su](https://jut.su/ken-deshita/season-2/episode-9.html) и [Shikimori](https://shikimori.io/animes/245-great-teacher-onizuka). Эти страницы приложение отклоняет как неподдерживаемые.

Для проверки без зависимости от сайтов на ПК и Android использовались тестовые MP4 и HLS. В KDE проверены уход в трей, завершение загрузки со скрытым окном и возврат окна. На Pixel 8 проверены фоновая загрузка, докачка, уведомление с прогрессом и переход из уведомления в очередь.
