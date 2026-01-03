const timeInput = document.getElementById('meeting-time');
const mainBtn = document.getElementById('get-video');

timeInput.addEventListener('change', () => {
    if (timeInput.value) {
        mainBtn.classList.add('active');
    }
});

mainBtn.addEventListener('click', function() {
    
    if (!timeInput.value) {
        alert("Калі ласка, абярыце час");
        return;
    }

    let viewed = JSON.parse(localStorage.getItem('viewed_videos') || "[]");
    
    let available = videoArchive.filter(v => !viewed.includes(v.url));
    
    if (available.length === 0) {
        alert("Вы паглядзелі ўсе 118 эпізодаў. Цыкл пачынаецца зноў.");
        viewed = [];
        available = videoArchive;
    }

    const video = available[Math.floor(Math.random() * available.length)];
    
    viewed.push(video.url);
    localStorage.setItem('viewed_videos', JSON.stringify(viewed));

    const [mins, secs] = video.duration.split(':').map(Number);
    const durationMs = (mins * 60 + secs) * 1000;
    
    const startTime = new Date(timeInput.value);
    const endTime = new Date(startTime.getTime() + durationMs);

    const formatGcal = (d) => d.toISOString().replace(/-|:|\.\d\d\d/g, "");
    
    const gUrl = `https://www.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent('Урок: ' + video.title)}&dates=${formatGcal(startTime)}/${formatGcal(endTime)}&details=${encodeURIComponent('Глядзець тут: ' + video.url)}&sf=true&output=xml`;

    // .ics файл
    const icsContent = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        `DTSTART:${formatGcal(startTime)}`,
        `DTEND:${formatGcal(endTime)}`,
        `SUMMARY:${video.title}`,
        `DESCRIPTION:Глядзець відэа: ${video.url}`,
        "END:VEVENT",
        "END:VCALENDAR"
    ].join("\n");
    
    const icsBlob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' });
    const icsUrl = URL.createObjectURL(icsBlob);

    const resultArea = document.getElementById('result-area');
    
    resultArea.innerHTML = `
        <div class="result-card">
            <a href="${video.url}" target="_blank" class="video-link">${video.title}</a>
            <p style="margin: 10px 0; color: #888;">Працягласць відэа: ${video.duration}</p>
            <div class="calendar-options">
                <a href="${gUrl}" target="_blank" class="btn-cal">Дадаць напамін у Google каляндар</a>
                <a href="${icsUrl}" download="lesson.ics" class="btn-cal">Дадаць напамін у Apple каляндар</a>
            </div>
        </div>
    `;
    
    setTimeout(() => {
        window.scrollTo({
            top: resultArea.offsetTop - 50,
            behavior: 'smooth'
        });
    }, 100);
});
