// Val's - Luxury Handcrafted - JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Auto close flash messages
    const flashMessages = document.querySelectorAll('.flash');
    flashMessages.forEach(flash => {
        setTimeout(() => {
            if (flash.parentNode) {
                flash.style.animation = 'slideOut 0.4s ease forwards';
                setTimeout(() => {
                    if (flash.parentNode) {
                        flash.remove();
                    }
                }, 400);
            }
        }, 5000);
    });

    // Add to cart animation
    const addToCartBtns = document.querySelectorAll('form[action*="adicionar-carrinho"] button');
    addToCartBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const originalText = this.innerHTML;
            this.innerHTML = '<span>Adicionado</span>';
            this.style.background = 'var(--gold)';
            this.style.borderColor = 'var(--gold)';
            this.style.color = 'var(--navy)';

            setTimeout(() => {
                this.innerHTML = originalText;
                this.style.background = '';
                this.style.borderColor = '';
                this.style.color = '';
            }, 2000);
        });
    });
});

// CSS adicional
const additionalCSS = `
@keyframes slideOut {
    from {
        opacity: 1;
        transform: translateX(0);
    }
    to {
        opacity: 0;
        transform: translateX(100%);
    }
}
`;

const style = document.createElement('style');
style.textContent = additionalCSS;
document.head.appendChild(style);

// ================================
// SISTEMA DE ZOOM
// ================================
let currentImageIndex = 0;
let images = [];
let zoomLevel = 1;
let isDragging = false;
let startX = 0;
let startY = 0;
let translateX = 0;
let translateY = 0;

function openImageModal(imageSrc, imageIndex, imageArray) {
    const modal = document.getElementById('imageModal');
    const modalImage = document.getElementById('modalImage');
    if (!modal || !modalImage) return;

    images = imageArray && imageArray.length > 0 ? imageArray : [imageSrc];
    currentImageIndex = imageIndex || 0;

    modalImage.src = images[currentImageIndex];
    modalImage.style.transform = 'scale(1) translate(0, 0)';
    zoomLevel = 1;
    translateX = 0;
    translateY = 0;

    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeImageModal() {
    const modal = document.getElementById('imageModal');
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
}

function zoomIn() {
    zoomLevel = Math.min(zoomLevel * 1.5, 5);
    updateImageTransform();
}

function zoomOut() {
    zoomLevel = Math.max(zoomLevel / 1.5, 0.5);
    updateImageTransform();
}

function resetZoom() {
    zoomLevel = 1;
    translateX = 0;
    translateY = 0;
    updateImageTransform();
}

function updateImageTransform() {
    const modalImage = document.getElementById('modalImage');
    if (modalImage) {
        modalImage.style.transform = 'scale(' + zoomLevel + ') translate(' + translateX + 'px, ' + translateY + 'px)';
        modalImage.classList.toggle('zoomed', zoomLevel > 1);
    }
}

function previousImage() {
    if (images.length > 1) {
        currentImageIndex = (currentImageIndex - 1 + images.length) % images.length;
        changeImage();
    }
}

function nextImage() {
    if (images.length > 1) {
        currentImageIndex = (currentImageIndex + 1) % images.length;
        changeImage();
    }
}

function changeImage() {
    const modalImage = document.getElementById('modalImage');
    if (modalImage) {
        modalImage.src = images[currentImageIndex];
        resetZoom();
    }
}

// Event listeners para o zoom
document.addEventListener('DOMContentLoaded', function() {
    // Fechar modal com ESC
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeImageModal();
        } else if (e.key === 'ArrowLeft') {
            previousImage();
        } else if (e.key === 'ArrowRight') {
            nextImage();
        } else if (e.key === '+' || e.key === '=') {
            zoomIn();
        } else if (e.key === '-') {
            zoomOut();
        } else if (e.key === '0') {
            resetZoom();
        }
    });

    // Arrastar imagem quando zoom > 1
    const modalImage = document.getElementById('modalImage');
    if (modalImage) {
        modalImage.addEventListener('mousedown', function(e) {
            if (zoomLevel > 1) {
                isDragging = true;
                startX = e.clientX - translateX;
                startY = e.clientY - translateY;
                e.preventDefault();
            }
        });

        document.addEventListener('mousemove', function(e) {
            if (isDragging && zoomLevel > 1) {
                translateX = e.clientX - startX;
                translateY = e.clientY - startY;
                updateImageTransform();
            }
        });

        document.addEventListener('mouseup', function() {
            isDragging = false;
        });
    }

    // Configurar miniaturas para abrir modal
    const thumbnails = document.querySelectorAll('.thumbnail');
    thumbnails.forEach(function(thumb, index) {
        thumb.addEventListener('click', function() {
            var imageSources = Array.from(thumbnails).map(function(t) { return t.src; });
            openImageModal(thumb.src, index, imageSources);
        });
    });

    // Configurar imagem principal para abrir modal
    const mainImage = document.querySelector('.main-image');
    if (mainImage) {
        mainImage.addEventListener('click', function() {
            var imageSources = Array.from(thumbnails).map(function(t) { return t.src; });
            openImageModal(mainImage.src, 0, imageSources);
        });
    }
});